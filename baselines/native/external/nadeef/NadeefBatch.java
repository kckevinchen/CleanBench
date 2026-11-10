/* Project-authored batch I/O and execution checks for the unmodified NADEEF API. */
import com.google.gson.*;
import qa.qcri.nadeef.core.datamodel.CleanPlan;
import qa.qcri.nadeef.core.datamodel.NadeefConfiguration;
import qa.qcri.nadeef.core.pipeline.CleanExecutor;
import qa.qcri.nadeef.core.pipeline.NodeCacheManager;
import qa.qcri.nadeef.core.pipeline.UpdateExecutor;
import qa.qcri.nadeef.core.utils.sql.DBConnectionPool;
import qa.qcri.nadeef.core.utils.sql.DBInstaller;
import qa.qcri.nadeef.tools.PerfReport;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.util.*;

public final class NadeefBatch {
    private static final Gson JSON = new GsonBuilder().serializeNulls().create();

    private static Object field(Object owner, String name) throws Exception {
        Field f = owner.getClass().getDeclaredField(name);
        f.setAccessible(true);
        return f.get(owner);
    }

    // The native pipeline catches exceptions; an exit code or progress bar is
    // insufficient evidence of completion. Observe, without changing, its state.
    private static void checkFlow(Object owner, String name) throws Exception {
        Object flow = field(owner, name);
        if (!"Stopped".equals(field(flow, "state").toString()) ||
            !field(flow, "currentFlowPosition").equals(((List<?>)field(flow, "nodeList")).size())) {
            throw new IllegalStateException("Native " + name + " did not finish all operators");
        }
    }

    private static Connection connect() throws Exception {
        return DBConnectionPool.createConnection(NadeefConfiguration.getDbConfig(), true);
    }

    private static int count(String sql) throws Exception {
        try (Connection c = connect(); Statement s = c.createStatement(); ResultSet r = s.executeQuery(sql)) {
            r.next();
            return r.getInt(1);
        }
    }

    private static long lastMetric(PerfReport.Metric metric) {
        List<Long> values = PerfReport.get(metric);
        if (values == null || values.isEmpty()) {
            throw new IllegalStateException("Native metric missing: " + metric);
        }
        return values.get(values.size() - 1);
    }

    private static List<List<String>> source(int width) throws Exception {
        List<List<String>> rows = new ArrayList<>();
        try (Connection c = connect(); Statement s = c.createStatement();
             ResultSet r = s.executeQuery("SELECT * FROM INPUT_DATA ORDER BY TID")) {
            while (r.next()) {
                if (r.getInt("TID") != rows.size() + 1) {
                    throw new IllegalStateException("Source row identity changed");
                }
                List<String> row = new ArrayList<>();
                for (int j = 0; j < width; j++) row.add(r.getString("C" + j));
                rows.add(row);
            }
        }
        return rows;
    }

    private static void importRows(JsonObject input) throws Exception {
        int width = input.get("n_columns").getAsInt();
        StringBuilder ddl = new StringBuilder("CREATE TABLE INPUT_DATA (TID INT PRIMARY KEY");
        List<String> placeholders = new ArrayList<>();
        placeholders.add("?");
        for (int j = 0; j < width; j++) {
            ddl.append(", C").append(j).append(" VARCHAR(8192)");
            placeholders.add("?");
        }
        ddl.append(")");
        try (Connection c = connect(); Statement s = c.createStatement()) {
            s.execute(ddl.toString());
            try (PreparedStatement p = c.prepareStatement(
                    "INSERT INTO INPUT_DATA VALUES (" + String.join(",", placeholders) + ")")) {
                int tid = 0;
                for (JsonElement item : input.getAsJsonArray("rows")) {
                    JsonArray row = item.getAsJsonArray();
                    if (row.size() != width) throw new IllegalArgumentException("Ragged source");
                    p.setInt(1, ++tid);
                    for (int j = 0; j < width; j++) p.setString(j + 2, row.get(j).getAsString());
                    p.addBatch();
                }
                p.executeBatch();
            }
        }
        if (!JSON.toJsonTree(source(width)).equals(input.getAsJsonArray("rows"))) {
            throw new IllegalStateException("Database import did not preserve exact source strings");
        }
    }

    private static List<List<Object>> violations(List<List<String>> current) throws Exception {
        List<List<Object>> cells = new ArrayList<>();
        try (Connection c = connect(); Statement s = c.createStatement();
             ResultSet r = s.executeQuery("SELECT DISTINCT TUPLEID, ATTRIBUTE, VALUE, TABLENAME FROM VIOLATION")) {
            while (r.next()) {
                int row = r.getInt(1) - 1;
                String attribute = r.getString(2);
                if (!"INPUT_DATA".equalsIgnoreCase(r.getString(4)) || !attribute.matches("C[0-9]+")) {
                    throw new IllegalStateException("Unexpected violation table or column");
                }
                int col = Integer.parseInt(attribute.substring(1));
                if (row < 0 || row >= current.size() || col >= current.get(row).size() ||
                    !Objects.equals(current.get(row).get(col), r.getString(3))) {
                    throw new IllegalStateException("Native violation export changed coordinates or values");
                }
                cells.add(Arrays.<Object>asList(row, col));
            }
        }
        return cells;
    }

    private static void run(String[] args) throws Exception {
        JsonObject input;
        try (Reader r = Files.newBufferedReader(Paths.get(args[0]), StandardCharsets.UTF_8)) {
            input = new JsonParser().parse(r).getAsJsonObject();
        }
        // Use NADEEF's supported embedded Derby connection directly. Bootstrap's
        // extra network server is unnecessary for a process-local in-memory DB.
        try (Reader r = Files.newBufferedReader(Paths.get(args[1]), StandardCharsets.UTF_8)) {
            NadeefConfiguration.initialize(r);
        }
        importRows(input);
        List<CleanPlan> plans;
        try (Reader r = Files.newBufferedReader(Paths.get(args[2]), StandardCharsets.UTF_8)) {
            plans = CleanPlan.create(r, NadeefConfiguration.getDbConfig());
        }
        if (plans.size() != input.get("n_rules").getAsInt() || plans.isEmpty()) {
            throw new IllegalStateException("Native rule compilation did not produce all rules");
        }
        List<CleanExecutor> executors = new ArrayList<>();
        UpdateExecutor updater = null;
        Map<String, Object> result = new LinkedHashMap<>();
        try {
            for (CleanPlan p : plans) executors.add(new CleanExecutor(p));
            updater = new UpdateExecutor(plans.get(0), NadeefConfiguration.getDbConfig());
            int changed, iterations = 0;
            List<List<Object>> initialDetections = new ArrayList<>();
            do {
                DBInstaller.cleanExecutionDB();
                PerfReport.clear();
                for (CleanExecutor e : executors) {
                    e.detect();
                    checkFlow(e, "detectFlow");
                    String rule = e.getCleanPlan().getRule().getRuleName();
                    int exported = count("SELECT COUNT(DISTINCT VID) FROM VIOLATION WHERE RID='" + rule + "'");
                    if (exported != lastMetric(PerfReport.Metric.ViolationExport)) {
                        throw new IllegalStateException("Native violation bulk load lost records");
                    }
                }
                List<List<Object>> detected = violations(source(input.get("n_columns").getAsInt()));
                if (iterations == 0) {
                    initialDetections = detected;
                    Map<String, Object> detection = new LinkedHashMap<>();
                    detection.put("status", "complete");
                    detection.put("initial_detections", initialDetections);
                    // Persist successful detection even if native repair later fails.
                    try (Writer w = Files.newBufferedWriter(Paths.get("detection.json"), StandardCharsets.UTF_8)) {
                        JSON.toJson(detection, w);
                    }
                }
                // No source update occurs between these phases; each native
                // repair reads only its own rule's violations, as in Console.run.
                for (CleanExecutor e : executors) {
                    int before = count("SELECT COUNT(*) FROM REPAIR");
                    e.repair();
                    checkFlow(e, "repairFlow");
                    int expected = e.<Integer>getRepairOutput();
                    if (count("SELECT COUNT(*) FROM REPAIR") - before != expected) {
                        throw new IllegalStateException("Native candidate repair export lost records");
                    }
                }
                updater.run();
                checkFlow(updater, "updateFlow");
                changed = updater.getUpdateCellCount();
                iterations++;
                // Preserve Console.run's exact stop condition, including <=.
            } while (changed != 0 && iterations <= NadeefConfiguration.getMaxIterationNumber());
            result.put("status", "complete");
            result.put("initial_detections", initialDetections);
            result.put("cleaned_rows", source(input.get("n_columns").getAsInt()));
            result.put("iterations", iterations);
            result.put("converged", changed == 0);
            try (Writer w = Files.newBufferedWriter(Paths.get(args[3]), StandardCharsets.UTF_8)) {
                JSON.toJson(result, w);
            }
        } finally {
            if (updater != null) updater.shutdown();
            for (CleanExecutor e : executors) e.shutdown();
            NodeCacheManager.getInstance().clear();
        }
    }

    public static void main(String[] args) {
        int exit = 0;
        try {
            if (args.length != 4) throw new IllegalArgumentException("input config plan output required");
            run(args);
        } catch (Throwable error) {
            error.printStackTrace();
            exit = 1;
        }
        System.exit(exit);
    }
}
