#pragma once

namespace plotter::web {

inline constexpr char kIndexHtml[] PROGMEM = R"HTML(
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Printrbot Bridge</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif}*{box-sizing:border-box}
body{margin:0;background:#08111b;color:#edf5fc}main{width:min(1050px,calc(100% - 24px));margin:20px auto 50px}
h1{margin:0 0 4px;font-size:clamp(28px,7vw,44px)}p{color:#9fb2c3}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:#111c28;border:1px solid #26394b;border-radius:16px;padding:16px;box-shadow:0 14px 35px #0005}
.card h2{margin:0 0 12px;font-size:18px}.status{display:grid;grid-template-columns:1fr auto;gap:8px 18px}
.label{color:#93a9bc}.value{text-align:right;font-weight:700}.good{color:#65e9a5}.warn{color:#ffd166}.bad{color:#ff7a8a}
button,input,textarea{width:100%;border:1px solid #385069;border-radius:10px;padding:11px;font:inherit}
input,textarea{background:#09121c;color:#edf5fc}textarea{min-height:150px;resize:vertical}.buttons{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
button{background:#256ca3;color:white;font-weight:700;cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}.pause{background:#8a631b}.cancel{background:#82404a}.danger{background:#aa2638}.secondary{background:#34495c}
progress{width:100%;height:18px;margin:10px 0}.log{background:#071019;border-radius:10px;padding:10px;min-height:230px;max-height:340px;overflow:auto;white-space:pre-wrap;font:12px ui-monospace,SFMono-Regular,monospace;color:#a9d3ef}
.small{font-size:13px;color:#8da3b6}.full{grid-column:1/-1}@media(max-width:760px){.grid{grid-template-columns:1fr}.full{grid-column:auto}}
</style>
</head>
<body><main>
<h1>Printrbot Bridge</h1>
<p>ESP32-C3 Wi-Fi transport for acknowledged Marlin jobs. Preview and G-code generation remain in the Python application.</p>
<div class="grid">
<section class="card">
<h2>Bridge status</h2>
<div class="status">
<div class="label">Firmware</div><div id="firmware" class="value">—</div>
<div class="label">Wi-Fi mode</div><div id="wifi" class="value">—</div>
<div class="label">Bridge address</div><div id="ip" class="value">—</div>
<div class="label">Marlin UART</div><div id="printer" class="value">—</div>
<div class="label">Job state</div><div id="state" class="value">—</div>
<div class="label">Commands</div><div id="commands" class="value">—</div>
<div class="label">Stored job</div><div id="bytes" class="value">—</div>
<div class="label">Active command</div><div id="active" class="value">—</div>
</div>
<progress id="progress" max="100" value="0"></progress>
<div id="message" class="small"></div>
</section>

<section class="card">
<h2>Upload reviewed G-code</h2>
<input id="jobFile" type="file" accept=".gcode,.gc,.txt,text/plain">
<textarea id="jobText" placeholder="Or paste reviewed G-code here"></textarea>
<button onclick="uploadJob()">Validate and store job</button>
<p class="small">Jobs are stored in ESP32 LittleFS, scanned line by line, and rejected if they contain heater, extrusion, tool-change, or embedded emergency-stop commands.</p>
</section>

<section class="card">
<h2>Job controls</h2>
<div class="buttons">
<button id="start" onclick="action('start')">Start</button>
<button id="pause" class="pause" onclick="action('pause')">Pause</button>
<button id="resume" class="secondary" onclick="action('resume')">Resume</button>
<button id="cancel" class="cancel" onclick="action('cancel')">Orderly cancel</button>
</div>
<button class="danger" onclick="emergency()">EMERGENCY STOP — M112</button>
<p class="small">The bridge forces a full <code>G28</code> home before every stored job, regardless of uploaded G-code. Pause and orderly cancellation occur between acknowledged commands. Emergency stop is immediate and requires resetting the Printrboard.</p>
</section>

<section class="card">
<h2>Non-moving printer queries</h2>
<div class="buttons">
<button class="secondary" onclick="queryPrinter('M115')">M115 firmware</button>
<button class="secondary" onclick="queryPrinter('M119')">M119 endstops</button>
<button class="secondary" onclick="queryPrinter('M114')">M114 position</button>
<button class="secondary" onclick="queryPrinter('M503')">M503 settings</button>
</div>
<p class="small">This endpoint accepts only a fixed list of non-moving status commands and is disabled while a job is active.</p>
</section>

<section class="card full">
<h2>UART activity</h2>
<div id="log" class="log">Waiting for bridge data…</div>
</section>

<section class="card full">
<h2>Optional home Wi-Fi</h2>
<div class="grid">
<div><label>Network name</label><input id="ssid" autocomplete="off"></div>
<div><label>Password</label><input id="password" type="password" autocomplete="new-password"></div>
</div>
<button class="secondary" onclick="saveWifi()">Save and restart</button>
<p class="small">The setup access point remains available. Do not connect this development firmware to an untrusted network; API authentication is not implemented yet.</p>
</section>
</div>
</main>
<script>
const $=id=>document.getElementById(id);let latest={};
async function request(url,options={}){const r=await fetch(url,options);const t=await r.text();let d={};try{d=JSON.parse(t)}catch{d={message:t}}if(!r.ok)throw new Error(d.error||d.message||('HTTP '+r.status));return d}
function formBody(values){const p=new URLSearchParams();Object.entries(values).forEach(([k,v])=>p.set(k,v));return p}
async function uploadJob(){
 try{
  const fd=new FormData();const file=$('jobFile').files[0];
  if(file)fd.append('job',file,file.name);else{const text=$('jobText').value;if(!text.trim())throw new Error('Choose a file or paste G-code.');fd.append('job',new Blob([text],{type:'text/plain'}),'pasted.gcode')}
  $('message').textContent='Uploading and validating…';await request('/api/job',{method:'POST',body:fd});$('message').textContent='Job validated and stored.';await poll();
 }catch(e){$('message').textContent=e.message}
}
async function action(name){try{await request('/api/job/'+name,{method:'POST'});await poll()}catch(e){$('message').textContent=e.message}}
async function emergency(){if(!confirm('Send M112 immediately? The Printrboard may require reset.'))return;try{await request('/api/emergency',{method:'POST'});await poll()}catch(e){$('message').textContent=e.message}}
async function queryPrinter(command){try{await request('/api/printer/query',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:formBody({command})});$('message').textContent=command+' sent; inspect UART activity.'}catch(e){$('message').textContent=e.message}}
async function saveWifi(){try{await request('/api/wifi',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:formBody({ssid:$('ssid').value,password:$('password').value})});$('message').textContent='Saved. Bridge is restarting…'}catch(e){$('message').textContent=e.message}}
function cls(state){return ['failed','emergency'].includes(state)?'value bad':['paused','cancelling'].includes(state)?'value warn':['ready','running','completed'].includes(state)?'value good':'value'}
async function poll(){
 try{const s=await request('/api/status');latest=s;$('firmware').textContent=s.firmware;$('wifi').textContent=s.wifi_mode;$('ip').textContent=s.ip;$('printer').textContent=s.printer_connected?'responding':'no response yet';$('printer').className=s.printer_connected?'value good':'value warn';$('state').textContent=s.job.state;$('state').className=cls(s.job.state);$('commands').textContent=s.job.completed+' / '+s.job.total;$('bytes').textContent=Math.round(s.job.bytes/1024)+' KiB';$('active').textContent=s.job.active||'—';$('progress').value=s.job.progress;$('message').textContent=s.job.error||'';$('log').textContent=s.log.join('\n')||'No UART lines yet.';$('log').scrollTop=$('log').scrollHeight;
  $('start').disabled=s.job.state!=='ready'&&!['completed','cancelled','failed'].includes(s.job.state);$('pause').disabled=s.job.state!=='running';$('resume').disabled=s.job.state!=='paused';$('cancel').disabled=!['ready','running','paused'].includes(s.job.state);
 }catch(e){$('message').textContent='Bridge unavailable: '+e.message}
}
poll();setInterval(poll,1000);
</script>
</body></html>
)HTML";

}  // namespace plotter::web
