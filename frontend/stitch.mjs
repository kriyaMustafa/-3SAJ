import fs from 'fs';

const backupPath = 'C:/Users/3SAJ/AppData/Roaming/Code/User/History/66c5cf81/ybRp.jsx';
const appPath = 'Z:/year3/projecj video translate backup/frontend/src/App.jsx';

const backupContent = fs.readFileSync(backupPath, 'utf-8');
const appContent = fs.readFileSync(appPath, 'utf-8');

// Find where "playing" is in the backup
const backupPlayingIndex = backupContent.indexOf('playing\\n');
if (backupPlayingIndex === -1) {
    console.log("Could not find playing in backup");
}

// In the backup, the line is:
//                                                   playing
//                                                     ? "bg-emerald-500 ...

const playingLineStr = '                                                  playing\\n';
const backupSplit = backupContent.split(playingLineStr);

if (backupSplit.length < 2) {
    console.log("Could not split backup by playing\\n");
    process.exit(1);
}

// The bottom half is everything after the first 'playing\n'
let bottomHalf = backupSplit[1];

// Make sure to remove the weird `playing` at the very end of ybRp.jsx if it's there
bottomHalf = bottomHalf.replace(/\\s*playing\\s*$/, '');

// Now replace "playing" in App.jsx with "playing\n" + bottomHalf
const appSplit = appContent.split(playingLineStr);

if (appSplit.length < 2) {
    console.log("Could not split app by playing\\n");
    // Just replace the literal "playing"
    const fallbackStr = "                                                  playing";
    const appFallback = appContent.split(fallbackStr);
    if (appFallback.length >= 2) {
        fs.writeFileSync(appPath, appFallback[0] + fallbackStr + '\\n' + bottomHalf);
        console.log("Stitched fallback!");
        process.exit(0);
    }
    process.exit(1);
}

const finalContent = appSplit[0] + playingLineStr + bottomHalf;
fs.writeFileSync(appPath, finalContent);
console.log("Successfully stitched 500 lines!");
