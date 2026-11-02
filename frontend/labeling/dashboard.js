const $ = (id) => document.getElementById(id);

async function loadRuns() {
  try {
    const response = await fetch('/api/runs');
    if (!response.ok) throw new Error('Could not load runs');
    const payload = await response.json();
    $('workspace').textContent = `Workspace: ${payload.project_root}`;
    $('runs').replaceChildren();
    for (const run of payload.runs) {
      const row = document.createElement('div');
      row.className = 'run';
      const name = document.createElement('strong');
      name.textContent = run.display_name || run.run_id;
      const info = document.createElement('span');
      info.textContent = `${run.n_sources} tables · ${run.clusters} candidates`;
      const label = document.createElement('a');
      label.textContent = 'Label';
      label.href = `./label.html?run=${encodeURIComponent(run.run_id)}`;
      row.append(name, info, label);
      $('runs').append(row);
    }
    if (!payload.runs.length) $('runs').textContent = 'No runs yet. Import CSVs above to start.';
  } catch (error) {
    $('runs').textContent = error.message;
  }
}

$('import-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $('message').textContent = 'Importing…';
  try {
    const sources = {};
    for (const file of $('csvs').files) {
      if (Object.hasOwn(sources, file.name)) throw new Error(`Duplicate CSV name: ${file.name}`);
      sources[file.name] = await file.text();
    }
    let candidates = null;
    if ($('candidates').files.length) {
      candidates = (await $('candidates').files[0].text()).split(/\r?\n/).filter((line) => line.trim()).map(JSON.parse);
    }
    const response = await fetch('/api/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: $('run-id').value, sources, candidates }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail));
    location.href = `./label.html?run=${encodeURIComponent(result.run_id)}`;
  } catch (error) {
    $('message').textContent = error.message;
    button.disabled = false;
  }
});
$('refresh').addEventListener('click', loadRuns);
loadRuns();
