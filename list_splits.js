const fs = require('fs');
const dir = 'E:/OpenIIT Data/evaluation_artifacts';
const files = fs.readdirSync(dir).filter(f => f.startsWith('ps3_eval') && f.endsWith('.json'));
files.forEach(f => {
    const content = fs.readFileSync(dir + '/' + f, 'utf8');
    const data = JSON.parse(content);
    console.log(f + ': split=' + data.run.config.split);
});