import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import speedy.model.algebra.operators.mainmemory.MainMemoryUpdateCell;
import it.unibas.lunatic.OperatorFactory;
import it.unibas.lunatic.Scenario;
import it.unibas.lunatic.model.chase.chasemc.DeltaChaseStep;
import it.unibas.lunatic.model.chase.chasemc.operators.RankSolutions;
import it.unibas.lunatic.model.chase.chasemc.usermanager.StandardUserManager;
import it.unibas.lunatic.model.chase.commons.operators.ChaserFactoryMC;
import it.unibas.lunatic.persistence.DAOMCScenario;
import speedy.model.algebra.operators.ITupleIterator;
import speedy.model.database.*;
import java.io.File;
import java.util.*;

/** I/O only: native chase and native solution scores are unchanged. */
public class NativeBridge {
    static List<Map<String,Object>> rows(IDatabase db) {
        List<Map<String,Object>> result = new ArrayList<>();
        for (String name : db.getTableNames()) {
            ITupleIterator it = db.getTable(name).getTupleIterator();
            while(it.hasNext()) {
                Tuple t = it.next();
                Map<String,Object> row = new TreeMap<>();
                for(Cell c : t.getCells()) {
                    if(c.isOID()) continue;
                    Map<String,String> value = new TreeMap<>();
                    value.put("value", c.getValue().toString());
                    value.put("type", c.getValue().getType());
                    row.put(c.getAttribute(), value);
                }
                result.add(row);
            }
            it.close();
        }
        return result;
    }
    public static void main(String[] args) throws Exception {
        Scenario scenario = new DAOMCScenario().loadScenario(args[0]);
        // XML is schema transport only. Restore exact dirty strings through the native
        // database API before any cleaning; XML's loader trims and maps blanks to null.
        JsonNode raw = new ObjectMapper().readTree(new File(args[2]));
        IDatabase target = scenario.getTarget();
        ITupleIterator sourceRows = target.getFirstTable().getTupleIterator();
        List<Cell> pending = new ArrayList<>();
        List<String> values = new ArrayList<>();
        while (sourceRows.hasNext()) {
            Tuple tuple = sourceRows.next();
            int row = -1;
            for (Cell cell : tuple.getCells()) if (cell.getAttribute().equals("rid")) row = Integer.parseInt(cell.getValue().toString());
            if (row < 0 || row >= raw.size()) throw new IllegalStateException("Invalid transport row");
            for (Cell cell : tuple.getCells()) if (cell.getAttribute().matches("C[0-9]+")) {
                pending.add(cell);
                values.add(raw.get(row).get(Integer.parseInt(cell.getAttribute().substring(1))).asText());
            }
        }
        sourceRows.close();
        MainMemoryUpdateCell writer = new MainMemoryUpdateCell();
        for (int i = 0; i < pending.size(); i++) writer.execute(new CellRef(pending.get(i)), new ConstantValue(values.get(i)), target);
        scenario.setUserManager(new StandardUserManager());
        scenario.getConfiguration().setExportSolutions(false);
        scenario.getConfiguration().setExportChanges(false);
        scenario.getConfiguration().setMaxNumberOfThreads(1);
        Map<String,Object> output = new TreeMap<>();
        output.put("before", rows(scenario.getTarget()));
        DeltaChaseStep root = ChaserFactoryMC.getChaser(scenario).doChase(scenario);
        new RankSolutions().rankSolutions(root.getChaseTree());
        List<DeltaChaseStep> solutions = root.getChaseTree().getRankedSolutions();
        solutions.sort(Comparator.comparingDouble(DeltaChaseStep::getScore).thenComparing(DeltaChaseStep::getId));
        output.put("solutions", solutions.size());
        if(!solutions.isEmpty()) {
            DeltaChaseStep chosen = solutions.get(0);
            IDatabase db = OperatorFactory.getInstance().getDatabaseBuilder(scenario).extractDatabase(chosen.getId(), chosen.getDeltaDB(), chosen.getOriginalDB(), scenario);
            output.put("after", rows(db));
            output.put("chosen_id", chosen.getId());
            output.put("score", chosen.getScore());
        }
        new ObjectMapper().writeValue(new File(args[1]), output);
    }
}
