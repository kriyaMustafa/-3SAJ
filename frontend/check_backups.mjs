import fs from 'fs';
import * as parser from '@babel/parser';

const files = [
    'hvWP.jsx', 'JEWj.jsx', 'u7mD.jsx', 'z0Or.jsx', 'TqSj.jsx', 'fE2z.jsx', 'ybRp.jsx'
];

for (const file of files) {
    const code = fs.readFileSync('C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/' + file, 'utf-8');
    try {
        parser.parse(code, { sourceType: 'module', plugins: ['jsx'] });
        console.log(file, 'COMPILES!');
    } catch(e) {
        console.log(file, 'FAILS:', e.message.split('\\n')[0]);
    }
}
