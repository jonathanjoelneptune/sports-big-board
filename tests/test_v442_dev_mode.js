'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'..','architecture/dev-mode.js'),'utf8');
const classes=new Set();const body={dataset:{},classList:{toggle:(n,on)=>on?classes.add(n):classes.delete(n),contains:n=>classes.has(n)}};
global.window=global;global.location={search:''};global.URLSearchParams=URLSearchParams;global.CustomEvent=function(n,o){this.type=n;this.detail=o?.detail};global.dispatchEvent=()=>{};global.document={body,readyState:'complete',addEventListener:()=>{}};
vm.runInThisContext(src,{filename:'dev-mode.js'});assert.equal(SBB_DEV_MODE.isEnabled(),false);assert.equal(classes.has('dev-mode'),false);SBB_DEV_MODE.set(true,'test');assert.equal(SBB_DEV_MODE.isEnabled(),true);assert.equal(body.dataset.sbbDev,'1');SBB_DEV_MODE.resetForLoad();assert.equal(SBB_DEV_MODE.isEnabled(),false);assert.equal(body.dataset.sbbDev,undefined);console.log('PASS: v4.4.2 Dev Mode is ephemeral and defaults OFF');
