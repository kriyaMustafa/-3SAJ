import fs from 'fs';
import * as parser from '@babel/parser';

let code = fs.readFileSync('C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/u7mD.jsx', 'utf-8');

code = code.replace(
  'const [pipelineState, setPipelineState] = createSignal({ status: "pending", progress: 0, chunks: { total: 0, completed: 0, failed: 0 }, segments: { total: 0, completed: 0 } });',
  ''
);

code = code.replace(
  'const id = state.selectedProjectId;\\r\\n    const id = selectedProjectId();',
  'const id = state.selectedProjectId || selectedProjectId();'
);

code = code.replace(
  'const id = state.selectedProjectId;\\n    const id = selectedProjectId();',
  'const id = state.selectedProjectId || selectedProjectId();'
);

code = code.replace(
  'const details = state.projectDetails;\\r\\n    const details = projectDetails();',
  'const details = state.projectDetails || projectDetails();'
);

code = code.replace(
  'const details = state.projectDetails;\\n    const details = projectDetails();',
  'const details = state.projectDetails || projectDetails();'
);

try {
    parser.parse(code, { sourceType: 'module', plugins: ['jsx'] });
    console.log('u7mD.jsx COMPILES PERFECTLY!');
    fs.writeFileSync('src/App.jsx', code);
    process.exit(0);
} catch(e) {
    console.log('u7mD.jsx FAILS AFTER FIX:', e.message);
    process.exit(1);
}
