'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {prepareDaemon, prepareWeb, credentials} = require('../mcsm/bootstrap.cjs');
test('fresh panel creates four Java instances; upgrade preserves identities and data', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mcnet-test-'));
  try {
    const daemon = path.join(root,'daemon');
    const web = path.join(root,'web');
    const config = prepareDaemon(daemon);
    assert.ok(config.key.length >= 32);
    let files = fs.readdirSync(path.join(daemon,'InstanceConfig'));
    assert.equal(files.length,4);
    for (const file of files) {
      const c = JSON.parse(fs.readFileSync(path.join(daemon,'InstanceConfig',file)));
      assert.equal(c.type,'minecraft/java');
      assert.equal(c.eventTask.autoRestart,false);
      assert.ok(c.startCommand.includes('/opt/mcnet/mcsm-container.cjs'));
    }
    const original = files[0];
    fs.renameSync(path.join(daemon,'InstanceConfig',original),path.join(daemon,'InstanceConfig','existing-id.json'));
    assert.equal(prepareDaemon(daemon).key,config.key);
    assert.ok(fs.existsSync(path.join(daemon,'InstanceConfig','existing-id.json')));
    assert.equal(fs.readdirSync(path.join(daemon,'InstanceConfig')).length,4);
    process.env.MCSM_PUBLIC_URL='https://mcsm.example.com';
    prepareWeb(web,daemon);
    const file = path.join(web,'RemoteServiceConfig',fs.readdirSync(path.join(web,'RemoteServiceConfig'))[0]);
    const node = JSON.parse(fs.readFileSync(file));
    assert.equal(node.ip,'wss://mcsm.example.com');
    assert.equal(node.port,443);
    assert.equal(node.prefix,'/daemon/');
    assert.equal(node.apiKey,config.key);
    assert.deepEqual(node.remoteMappings,[]);
    delete process.env.MCSM_PUBLIC_URL;
    prepareWeb(web,daemon);
    assert.equal(JSON.parse(fs.readFileSync(file)).ip,node.ip);
  } finally {delete process.env.MCSM_PUBLIC_URL; fs.rmSync(root,{recursive:true,force:true});}
});

test('generated administrator passwords meet the panel policy', () => {
  for (let i=0;i<100;i++) {
    const p=credentials().password;
    assert.ok(p.length >= 9 && p.length <= 36);
    assert.match(p, /(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])/);
  }
});
