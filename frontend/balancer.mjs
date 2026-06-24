import fs from 'fs';
import * as parser from '@babel/parser';

let code = fs.readFileSync('Z:/year3/projecj video translate backup/frontend/src/App.jsx', 'utf-8');
const suffix = `playing ? "bg-emerald-500 text-emerald-950" : "bg-slate-800 text-slate-300"}\`>Play</button>
</div></div></div></div>);}}</For></div>
<button type="button" class="w-full py-3 mt-4 bg-amber-500 font-black rounded-xl text-sm">Submit</button>
</Show></div>);})()}</div></Show></Show></div></div></div></div></div></div>);};
export default App;
`;

let baseCode = code.substring(0, code.lastIndexOf('playing')) + suffix;

let bestCode = baseCode;
let success = false;

for (let i = 0; i < 20; i++) {
    try {
        parser.parse(bestCode, { sourceType: 'module', plugins: ['jsx'] });
        success = true;
        break;
    } catch (e) {
        let msg = e.message;
        if (msg.includes("Expected corresponding JSX closing tag for <")) {
            let match = msg.match(/for <(.*?)>/);
            if (match && match[1]) {
                let tag = `</${match[1]}>`;
                bestCode = bestCode.replace(/\\s*\\);\\s*\\};\\s*export default App;\\s*$/, `\n${tag}\n);\n};\nexport default App;\n`);
            }
        } else if (msg.includes('Unexpected token, expected "}"')) {
             bestCode = bestCode.replace(/\\s*\\);\\s*\\};\\s*export default App;\\s*$/, `\n}\n);\n};\nexport default App;\n`);
        } else if (msg.includes('Unexpected token')) {
             bestCode = bestCode.replace(/<\\/div>\\s*\\n\\s*\\);\\s*\\};\\s*export default App;\\s*$/, `\n);\n};\nexport default App;\n`);
        } else {
            console.error("Unknown error:", msg);
            process.exit(1);
        }
    }
}

if (success) {
    fs.writeFileSync('Z:/year3/projecj video translate backup/frontend/src/App.jsx', bestCode);
    console.log("SUCCESS");
} else {
    console.log("FAILED");
}
