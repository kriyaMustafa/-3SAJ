import fs from 'fs';
import * as parser from '@babel/parser';

let code = fs.readFileSync('src/App.jsx', 'utf-8');

const marker = 'Submit All Parts\\n                                  </button>\\n                                </div>\\n';
const idx = code.indexOf('Submit All Parts');
const real_idx = code.indexOf('</div>', idx) + 6;

code = code.substring(0, real_idx);

let currentClosing = [];

for (let i=0; i<20; i++) {
    let testCode = code + '\\n' + currentClosing.join('\\n') + '\\n  );\\n}\\nexport default App;\\n';
    try {
        parser.parse(testCode, { sourceType: 'module', plugins: ['jsx'] });
        console.log('SUCCESS!');
        fs.writeFileSync('src/App.jsx', testCode);
        process.exit(0);
    } catch(e) {
        let msg = e.message;
        let match = msg.match(/Unexpected token, expected "(.*)"/);
        if (match) {
            currentClosing.push(match[1]);
        } else if (msg.includes('Unexpected token')) {
             match = msg.match(/Expected corresponding JSX closing tag for <(.*?)>/);
             if (match) {
                 currentClosing.push(`</${match[1]}>`);
             } else {
                 console.log("Unknown error:", msg);
                 process.exit(1);
             }
        } else if (msg.includes('Expected corresponding JSX closing tag')) {
             match = msg.match(/Expected corresponding JSX closing tag for <(.*?)>/);
             if (match) {
                 currentClosing.push(`</${match[1]}>`);
             } else {
                 console.log("Unknown JSX error:", msg);
                 process.exit(1);
             }
        } else if (msg.includes('Unterminated JSX contents')) {
             // Try pushing a div
             currentClosing.push('</div>');
        } else {
            console.log("Unhandled error format:", msg);
            process.exit(1);
        }
    }
}
console.log("Failed after 20 iterations", currentClosing);
