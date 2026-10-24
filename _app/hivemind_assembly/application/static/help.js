// Plain hover descriptions for every dashboard button, including buttons added later.
(() => {
  const byId = {
    'native-all': 'Open one sign-in window per account (ChatGPT, Claude), then set up each assistant.',
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
    'knowledge-curate': 'Let the adviser read the selected material and sort it into categories.',
    'optimize-workflow': 'Look for a faster way to do the chosen job; HA switches only if it is correct and faster.',
    'backup': 'Save a backup copy of all your HA data.',
    'install': 'Download and install everything HA uses, in one step. Progress shows below.',
    'verify-foundations': 'Check that the helper tools are installed correctly.',
    'github-auto': 'Connect HA to your GitHub account step by step.',
    'github-cancel': 'Stop the GitHub sign-in that is in progress.',
    'github-check': 'Check that the saved GitHub connection still works.',
    'github-disconnect': 'Remove the GitHub connection from this computer.',
    'save-config': 'Save all settings on this page.',
    'trace-export': 'Download the matching log entries as a file.',
    'trace-viewer': 'Send logs to a trace viewer running on this computer (for developers).',
    'trace-more': 'Show more log entries.',
    'mcp-config': 'Show the settings other apps need to connect to HA.',
    'quick-start': 'Open a free temporary web address so ChatGPT and Claude can reach HA.',
    'quick-stop': 'Close the web address. Work in HA continues.',
    'quick-copy': 'Copy the address to paste into ChatGPT or Claude.',
    'quick-chatgpt': 'Connect ChatGPT to HA by itself: start the connection, add HA in ChatGPT, approve it.',
    'quick-claude': 'Connect Claude to HA by itself: start the connection, add HA in Claude, approve it.',
    'quick-manual-chatgpt': 'Open ChatGPT\'s connector settings and show what to enter by hand.',
    'quick-manual-claude': 'Open Claude\'s connector settings and show what to enter by hand.',
    'quick-code-show': 'Show a one-time code for HA\'s approval page.',
    'quick-revoke': 'Remove access for every connected ChatGPT and Claude chat.',
    'local-apps': 'Add HA to Claude Desktop and Codex on this computer.',
    'permanent-off': 'Stop using the permanent address and go back to the temporary one.',
    'quick-reconnect': 'Replace and approve the HA connector in ChatGPT and Claude now, using HA\'s assistant windows.',
    'helper-open-extensions': 'Open a new Chrome window and type chrome://extensions into it for you.',
    'helper-copy-url': 'Copy chrome://extensions to paste into a new Chrome tab.',
    'helper-open-folder': 'Show the helper folder to choose in Load unpacked.',
    'helper-copy': 'Copy the helper folder to choose it in Load unpacked.',
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
      overview: 'Summary, getting started and activity logs.',
      projects: 'Projects, their files and tests, and results and backups.',
      routes: 'The AI assistants, their usage, and knowledge and skills.',
      settings: 'Tools, GitHub, connections and other settings.',
    },
    go: {
      projects: 'Go to Projects.',
      workspace: 'Go to the project files.',
      routes: 'Go to AI assistants.',
      settings: 'Go to Settings.',
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
    nativeSetup: 'Open this assistant\'s tab and set it up step by step.',
    nativeShow: 'Switch to this assistant\'s tab in Chrome.',
    nativeSnapshot: 'See a picture of what HA sees in this assistant\'s tab.',
    note: 'Save your note.',
    probe: 'Check whether this assistant is working.',
    reconcile: 'Check whether this saved action finished.',
    rollback: 'Undo this learned item.',
    share: 'Allow this lesson to be sent to the assistants when testing whether it helps.',
    unshare: 'Keep this lesson on this computer only.',
    gameAction: 'Play this action in the game.',
    gameReplay: 'Load this finding\'s exact inputs and replay them.',
    gameShrink: 'Find the fewest inputs that still cause this problem.',
    gamePackage: 'Show the frames and game state just before the problem.',
    gameSave: 'Save these inputs as a regression test.',
  };
  const byText = {
    'Create project': 'Create a new project.',
    'Save to GitHub': 'Link this project to a GitHub repository.',
    'Save limit': 'Save the request limit.',
    'Add file to project': 'Copy the chosen file into the project.',
    'Save tests': 'Save these tests for this project.',
    'Run on GitHub': 'Start the run, or continue it.',
    'Save checks': 'Save the tests that decide when the project is done.',
    'Open file': 'Open the selected file.',
    'Add category': 'Create a new category.',
    'Add to categories': 'Put the selected material in these categories.',
    'Save project categories': 'Choose which categories this task can use.',
    'Add document': 'Add this document to HA\'s reference material.',
    'Save experiment settings': 'Save the learning settings.',
    'Prepare practice set': 'Prepare a set of test examples.',
    'Test, and keep it if better': 'Test the candidate and use it if it does better.',
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
    'Save': 'Save these choices.',
    'Close': 'Close this window.',
    'Set up permanent address': 'Create the free Cloudflare Worker that gives HA a permanent address.',
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
