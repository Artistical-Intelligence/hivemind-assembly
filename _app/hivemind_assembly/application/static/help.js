// Plain hover descriptions for every dashboard button, including buttons added later.
(() => {
  const byId = {
    'native-all': 'Open sign-in windows for each AI assistant HA works with.',
    'verify': 'Run a quick built-in self-test.',
    'native-test-run': 'Run the saved tests for this project now.',
    'native-test-results': 'Show the results of the most recent test run.',
    'native-test-revoke': 'Turn off these tests for this project.',
    'hosted-new-request': 'Make a fresh request number for a new run.',
    'workspace-pause': 'Pause the project so you can edit its files safely.',
    'workspace-refresh': 'Reload the list of files.',
    'file-new': 'Create a new empty text file.',
    'file-save': 'Save your changes to this file.',
    'file-discard': 'Throw away unsaved changes to this file.',
    'file-download': 'Download the saved copy of this file.',
    'guided-add-case': 'Add another test input.',
    'guided-pin': 'Save these tests as the project\'s official tests.',
    'workspace-check': 'Run the project\'s tests now.',
    'workspace-last-result': 'Show the most recent test result.',
    'workspace-captures': 'Look at the recorded test output in detail.',
    'workspace-suite': 'Load the test file into the test setup form.',
    'knowledge-curate': 'Let HA sort the selected material into categories.',
    'optimize-workflow': 'Test whether a faster way of working is still correct.',
    'backup': 'Save a backup copy of all your HA data.',
    'install': 'Download and install everything HA uses, in one step. Progress shows below.',
    'verify-foundations': 'Check that the helper tools are installed correctly.',
    'github-auto': 'Connect HA to your GitHub account step by step.',
    'github-cancel': 'Stop the GitHub sign-in that is in progress.',
    'github-check': 'Check that the saved GitHub connection still works.',
    'github-disconnect': 'Remove the GitHub connection from this computer.',
    'save-config': 'Save all settings on this page.',
    'trace-export': 'Download the matching log entries as a file.',
    'trace-viewer': 'Send the next set of logs to the log viewer on this computer.',
    'trace-more': 'Show more log entries.',
    'mcp-config': 'Show the settings other apps need to connect to HA.',
    'tunnel-doctor': 'Check that the connection settings are correct.',
    'tunnel-start': 'Turn the private connection on.',
    'tunnel-stop': 'Turn the private connection off.',
    'tunnel-forget': 'Delete the saved connection key.',
    'mcp-discover': 'List the tools this connection offers.',
    'mcp-metadata-generate': 'Create the public info file this connection needs.',
    'mcp-oauth-forget': 'Remove the sign-in for this connection.',
    'mcp-forget': 'Delete the saved password or key for this connection.',
    'cloud-connect': 'Give HA permission to use your GitHub cloud machines.',
    'cloud-list': 'Reload the list of your cloud machines.',
    'cloud-machines': 'Show which machine sizes you can choose.',
    'cloud-recover-creation': 'Check on a cloud machine that was being created.',
    'game-load': 'Load this project\'s game contract and show its first frame.',
    'game-restart': 'Start the game again from the beginning.',
    'game-undo': 'Go back to the moment before your last action.',
    'game-save': 'Save the inputs you played as a regression test.',
    'game-explore': 'Let HA try many action sequences to look for problems.',
    'game-compare': 'Replay your inputs on the original and the rebuild and compare every tick.',
    'game-regressions': 'Replay every saved regression on the current rebuild.',
  };
  const byData = {
    tab: {
      overview: 'Summary of HA and quick start.',
      projects: 'Create and manage projects.',
      workspace: 'View and edit project files and try examples.',
      routes: 'Set up the AI assistants HA works with.',
      knowledge: 'Reference material and what HA has learned.',
      evidence: 'Results, backups and recovering interrupted work.',
      traces: 'Detailed activity logs.',
      connections: 'Connect other apps and cloud machines.',
      settings: 'Install tools and change settings.',
    },
    go: {
      projects: 'Go to Projects & tasks.',
      workspace: 'Go to Project files.',
      routes: 'Go to Native team setup.',
    },
    goalAction: {
      start: 'Start working on this project.',
      resume: 'Continue a paused project.',
      pause: 'Pause the project after the current step.',
      clear: 'Stop working on this project after the current step.',
    },
    action: {
      pause: 'Pause this task.',
      resume: 'Continue this task.',
      cancel: 'Cancel this task.',
    },
  };
  const byAttr = {
    starter: 'Create a ready-made example project.',
    go: 'Go to that page.',
    file: 'Open this file.',
    removeCase: 'Remove this test input.',
    evaluationResume: 'Try the unfinished runs again.',
    hostedCancel: 'Cancel this run.',
    hostedRefresh: 'Check the latest status of this run.',
    nativeRenew: 'Start a fresh conversation for this assistant.',
    nativeSetup: 'Open or set up this assistant\'s sign-in window.',
    note: 'Save your note.',
    probe: 'Check whether this assistant is working.',
    reconcile: 'Check whether this saved action finished.',
    rollback: 'Undo this learned item.',
    share: 'Allow this item to be used in tests with the AI assistants.',
    unshare: 'Keep this item on this computer only.',
    gameAction: 'Play this action in the game.',
    gameReplay: 'Load this finding\'s exact inputs and replay them.',
    gameShrink: 'Find the fewest inputs that still cause this problem.',
    gamePackage: 'Show the frames and game state just before the problem.',
    gameSave: 'Save these inputs as a regression test.',
  };
  const byText = {
    'Create project': 'Create a new project.',
    'Connect GitHub repository': 'Link this project to a GitHub repository.',
    'Save request limit': 'Save the request limit.',
    'Add file to project': 'Copy the chosen file into the project.',
    'Save tests': 'Save these tests for this project.',
    'Start or continue run': 'Start the run, or continue it.',
    'Save completion tests': 'Save the tests that decide when the project is done.',
    'Open file': 'Open the selected file.',
    'Add category': 'Create a new category.',
    'Add to categories': 'Put the selected material in these categories.',
    'Save task categories': 'Choose which categories this task can use.',
    'Add document': 'Add this document to HA\'s reference material.',
    'Save learning settings': 'Save the learning settings.',
    'Prepare test set': 'Prepare a set of test examples.',
    'Test and adopt if better': 'Test the candidate and use it if it does better.',
    'Connect with Client ID': 'Connect to GitHub using your own app ID.',
    'Save GitHub settings': 'Save the GitHub settings.',
    'Search': 'Search the logs.',
    'Save access': 'Save who can connect to HA.',
    'Add to app': 'Add HA to the other app\'s settings.',
    'Save tunnel settings': 'Save the private connection settings.',
    'Save connection': 'Save this connection.',
    'Sign in': 'Sign in to this connection in your browser.',
    'Save key': 'Save the password or key for this connection.',
    'Save cloud settings': 'Save these settings.',
    'Create Codespace': 'Create a new cloud machine.',
    'Run action': 'Do the chosen action on this cloud machine.',
    'Run job': 'Send this job to the cloud machine.',
    'Copy result into project': 'Copy the job\'s result into the project.',
    'Jump to first difference': 'Jump to the first place where results differ.',
    'Check request': 'Check on this cloud machine request.',
    'Check status': 'Check the latest status of this job.',
    'Cancel': 'Cancel this job.',
    'Show result': 'Show this job\'s result.',
  };
  function describe(b) {
    if (b.id && byId[b.id]) return byId[b.id];
    for (const [key, table] of Object.entries(byData)) {
      const value = b.dataset[key];
      if (value !== undefined && table[value]) return table[value];
    }
    for (const [key, text] of Object.entries(byAttr)) if (b.dataset[key] !== undefined) return text;
    const label = b.textContent.trim();
    if (byText[label]) return byText[label];
    if (/^Download .* capture$/.test(label)) return 'Download this recording.';
    return '';
  }
  function apply(root) {
    const buttons = root.matches?.('button') ? [root] : root.querySelectorAll?.('button') || [];
    for (const b of buttons) {
      if (b.title) continue;
      const text = describe(b);
      if (text) b.title = text;
    }
  }
  window.haDescribeButton = describe;
  apply(document);
  new MutationObserver(records => {
    for (const r of records) for (const n of r.addedNodes) if (n.nodeType === 1) apply(n);
  }).observe(document.body, {childList: true, subtree: true});
})();
