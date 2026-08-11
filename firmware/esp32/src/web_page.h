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
.status-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px}.status-tile{background:#0b1621;border:1px solid #26394b;border-radius:10px;padding:10px}.status-tile .label{display:block;font-size:12px;margin-bottom:4px}.status-tile .value{display:block;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.status-details{margin-top:10px;border-top:1px solid #26394b;padding-top:8px}.status-details summary{cursor:pointer;color:#c6d8e8;font-weight:700}.section-kicker{color:#65e9a5;font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px}.workflow-note{margin:0 0 12px;color:#9fb2c3}.flow-card{min-height:100%}
.advanced-panel{margin-top:0}.advanced-panel>summary{cursor:pointer;color:#c6d8e8;font-size:18px;font-weight:700;list-style-position:inside}.advanced-panel[open]>summary{margin-bottom:14px}
.label{color:#93a9bc}.value{text-align:right;font-weight:700}.good{color:#65e9a5}.warn{color:#ffd166}.bad{color:#ff7a8a}
button,input,textarea{width:100%;border:1px solid #385069;border-radius:10px;padding:11px;font:inherit}
input,textarea{background:#09121c;color:#edf5fc}textarea{min-height:150px;resize:vertical}.buttons{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
button{background:#256ca3;color:white;font-weight:700;cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}.pause{background:#8a631b}.cancel{background:#82404a}.danger{background:#aa2638}.secondary{background:#34495c}
progress{width:100%;height:18px;margin:10px 0}.log{background:#071019;border-radius:10px;padding:10px;min-height:230px;max-height:340px;overflow:auto;white-space:pre-wrap;font:12px ui-monospace,SFMono-Regular,monospace;color:#a9d3ef}
.small{font-size:13px;color:#8da3b6}.full{grid-column:1/-1}.gcode-preview{background:#071019;border:1px solid #26394b;border-radius:12px;padding:10px;min-height:300px;display:grid;place-items:center;cursor:grab;touch-action:none}.gcode-preview.dragging{cursor:grabbing}.gcode-preview svg{width:100%;height:auto;max-height:620px}.preview-stats{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.preview-stat{background:#1b2b3b;border-radius:8px;padding:7px 9px;color:#c6d8e8}.preview-warning{color:#ffb4bd;font-weight:700}.preview-key{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px}.preview-key span{display:inline-flex;align-items:center;gap:5px}.swatch{width:22px;height:3px;display:inline-block}.swatch.ink{background:#65e9a5}.swatch.travel{height:0;border-top:2px dashed #8daecc}.offset-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0}.offset-grid label{display:block;margin-bottom:4px}@media(max-width:760px){.grid{grid-template-columns:1fr}.full{grid-column:auto}.offset-grid{grid-template-columns:1fr}}
.placement-actions{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:8px}@media(max-width:760px){.status-summary{grid-template-columns:repeat(2,1fr)}.placement-actions{grid-template-columns:1fr}}
.workflow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0;color:#9fb2c3}.workflow-step{border:1px solid #385069;border-radius:999px;padding:6px 10px}.workflow-arrow{color:#65e9a5}
</style>
</head>
<body><main>
<h1>Printrbot Bridge</h1>
<p class="workflow-note">Prepare a plot in three steps: load the draft, review it, then generate and plot the validated job.</p>
<div class="grid">
<section class="card">
<div class="section-kicker">Live status</div><h2>Printer status</h2>
<div class="status-summary">
<div class="status-tile"><span class="label">Run state</span><span id="state" class="value">—</span></div>
<div class="status-tile"><span class="label">Commands</span><span id="commands" class="value">—</span></div>
<div class="status-tile"><span class="label">Stored job</span><span id="bytes" class="value">—</span></div>
<div class="status-tile"><span class="label">Active command</span><span id="active" class="value">—</span></div>
</div>
<progress id="progress" max="100" value="0"></progress>
<div id="message" class="small"></div>
<details class="status-details">
<summary>Connection details</summary>
<div class="status">
<div class="label">Firmware</div><div id="firmware" class="value">—</div>
<div class="label">Wi-Fi mode</div><div id="wifi" class="value">—</div>
<div class="label">Bridge address</div><div id="ip" class="value">—</div>
<div class="label">Marlin UART</div><div id="printer" class="value">—</div>
</div>
 </details>
</section>

<section class="card flow-card">
<div class="section-kicker">Step 1</div><h2>Load a draft G-code</h2>
<input id="jobFile" type="file" accept=".gcode,.gc,.txt,text/plain">
<textarea id="jobText" placeholder="Or paste reviewed G-code here"></textarea>
<button onclick="uploadDraft()">Save draft G-code</button>
<p class="small">Choosing a file loads it into the editor. Edit the G-code above, save the draft, review the preview, then validate the final job.</p>
</section>

<section class="card full">
<div class="section-kicker">Preview</div><h2>Review the bed and print area</h2>
<div id="gcodeMeta" class="small">Paste or choose G-code to inspect its actual XY moves before storing it.</div>
<div id="gcodeStats" class="preview-stats"></div>
<div id="gcodePreview" class="gcode-preview"><div class="small">No G-code loaded.</div></div>
<div class="preview-key"><span><i class="swatch ink"></i>Pen-down drawing</span><span><i class="swatch travel"></i>Pen-up travel</span><span>Bed: 152.4 × 152.4 mm</span></div>
<p class="small">The preview uses the machine bed, 10 mm grid, travel paths, and a red print-area box. The home travel line is hidden for clarity.</p>
<div class="offset-grid"><div><label for="offsetX">Move whole drawing X (mm)</label><input id="offsetX" type="number" step="0.1" value="0"></div><div><label for="offsetY">Move whole drawing Y (mm)</label><input id="offsetY" type="number" step="0.1" value="0"></div></div>
<div class="placement-actions"><button class="secondary" onclick="applyOffset()">Apply exact placement</button><button class="secondary" onclick="resetOffset()">Reset move fields</button></div>
<p class="small">Drag the red print-area box to move the entire drawing, or enter an exact X/Y move above. Releasing a drag applies the move to this one G-code draft.</p>
</section>

<section class="card full">
<div class="section-kicker">Step 2</div><h2>Generate, validate, and plot</h2>
<div class="offset-grid"><div><label for="drawSpeed">Drawing speed (mm/min)</label><input id="drawSpeed" type="number" min="60" max="7500" step="50" value="1200"></div><div><label for="travelSpeed">Travel speed (mm/min)</label><input id="travelSpeed" type="number" min="60" max="7500" step="50" value="3000"></div><div><label for="zSpeed">Pen lift speed (mm/min)</label><input id="zSpeed" type="number" min="30" max="300" step="10" value="300"></div></div>
<p class="small">Lower drawing speed helps ink transfer. Travel speed controls pen-up moves; pen lift speed controls Z motion. Values are clamped to the bridge safety limits before validation.</p>
<button onclick="generateAndValidateFinal()">Validate and store final G-code</button>
<p class="small">The current loaded draft is validated and stored as the runnable job. Once validation succeeds, Start becomes the next action.</p>
<div class="buttons">
<button id="start" onclick="action('start')">Start</button>
<button id="pause" class="pause" onclick="action('pause')">Pause</button>
<button id="resume" class="secondary" onclick="action('resume')">Resume</button>
<button id="cancel" class="cancel" onclick="action('cancel')">Orderly cancel</button>
</div>
<button class="danger" onclick="emergency()">EMERGENCY STOP — M112</button>
<p class="small">The bridge forces a full <code>G28</code> home before every stored job, regardless of uploaded G-code. Pause and orderly cancellation occur between acknowledged commands. Emergency stop is immediate and requires resetting the Printrboard.</p>
</section>

<details class="card full advanced-panel">
<summary>Diagnostics, printer queries, and Wi-Fi settings</summary>
<div class="grid">
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
<p class="small">The setup access point remains available. This local bridge has no request-level authentication; keep it on a trusted local network and never expose it to the public internet.</p>
</section>
</div>
</details>
</div>
</main>
<script>
const $=id=>document.getElementById(id);let latest={};
const BED={xmin:0,xmax:152.4,ymin:0,ymax:152.4,margin:8};
function gword(line,letter){const match=line.match(new RegExp('(?:^|\\s)'+letter+'\\s*([-+]?\\d*\\.?\\d+)','i'));return match?Number(match[1]):null}
function parseGcode(text,offsetX=0,offsetY=0){
 let x=0,y=0,z=5,absolute=true,penDown=false;const segments=[];let moves=0,drawMoves=0,travelMoves=0,outOfBed=0;
 for(const source of text.split(/\r?\n/)){
  const comment=(source.match(/;.*$/)||[''])[0].toLowerCase();
  const line=source.replace(/\([^)]*\)/g,'').replace(/;.*$/,'').trim();if(!line)continue;
  const command=(line.match(/^([GMT])\s*(\d+)/i)||[]).slice(1).join('').toUpperCase();
  if(command==='G90'){absolute=true;continue} if(command==='G91'){absolute=false;continue}
  if(command==='G28'){x=0;y=0;z=5;penDown=false;continue}
  if(command!=='G0'&&command!=='G1')continue;
  const oldX=x,oldY=y;const nextX=gword(line,'X'),nextY=gword(line,'Y'),nextZ=gword(line,'Z');
  if(nextZ!==null)z=absolute?nextZ:z+nextZ;
  if(nextX!==null)x=absolute?nextX:x+nextX;if(nextY!==null)y=absolute?nextY:y+nextY;
  // Z is the authoritative state for generated jobs. Comments are a
  // compatibility fallback for imported files that use a different safe-Z
  // convention. This keeps G1 XY strokes from being misreported as travel.
  if(nextZ!==null)penDown=z<=0.5;
  if(/pen\s+down/.test(comment))penDown=true;
  if(/pen\s+up|air\s+plot/.test(comment))penDown=false;
  if(nextX===null&&nextY===null)continue;
  moves++;const ink=penDown&&command==='G1';if(ink)drawMoves++;else travelMoves++;
  const shifted={x1:oldX+offsetX,y1:oldY+offsetY,x2:x+offsetX,y2:y+offsetY};const outside=[shifted.x1,shifted.y1,shifted.x2,shifted.y2].some((v,i)=>i%2===0?(v<BED.xmin||v>BED.xmax):(v<BED.ymin||v>BED.ymax));if(outside)outOfBed++;
  const homeTravel=!penDown&&oldX===0&&oldY===0;
  segments.push({...shifted,ink,outside,homeTravel});
 }
 return {segments,moves,drawMoves,travelMoves,outOfBed};
}
async function generateAndValidateFinal(){await validateFinalJob()}
function renderGcodePreview(text){
 const offsetX=Number($('offsetX').value)||0,offsetY=Number($('offsetY').value)||0;const result=parseGcode(text,offsetX,-offsetY);const syy=y=>BED.ymax-y;
 const inkSegments=result.segments.filter(s=>s.ink);let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;for(const s of inkSegments){minX=Math.min(minX,s.x1,s.x2);maxX=Math.max(maxX,s.x1,s.x2);minY=Math.min(minY,s.y1,s.y2);maxY=Math.max(maxY,s.y1,s.y2)}
 const svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -18 188.4 188.4">','<rect x="-18" y="-18" width="188.4" height="188.4" fill="#ffffff"/>','<rect x="0" y="0" width="152.4" height="152.4" fill="#f8fbfd" stroke="#536b7d" stroke-width="0.8"/>'];
 for(let userY=0;userY<=150;userY+=10){const displayY=userY;svg.push('<path d="M '+userY+' 0 V 152.4 M 0 '+displayY+' H 152.4" fill="none" stroke="#d5e0e8" stroke-width="0.18"/>');svg.push('<path d="M '+userY+' -3 V 0" fill="none" stroke="#536b7d" stroke-width="0.35"/>');svg.push('<path d="M '+userY+' 152.4 V 155.4" fill="none" stroke="#536b7d" stroke-width="0.35"/>');svg.push('<path d="M -3 '+displayY+' H 0" fill="none" stroke="#536b7d" stroke-width="0.35"/>');svg.push('<path d="M 152.4 '+displayY+' H 155.4" fill="none" stroke="#536b7d" stroke-width="0.35"/>');svg.push('<text x="'+(userY-1.7)+'" y="-6" text-anchor="middle" fill="#536b7d" font-size="2.5">'+userY+'</text>');svg.push('<text x="-5" y="'+(displayY+0.9)+'" text-anchor="end" fill="#536b7d" font-size="2.5">'+userY+'</text>')}
 svg.push('<text x="0" y="-12" fill="#536b7d" font-size="3.2" font-weight="700">HOME / X0 Y0</text>','<text x="152.4" y="-12" text-anchor="end" fill="#536b7d" font-size="3.2" font-weight="700">X152.4 Y0</text>','<text x="0" y="163" fill="#536b7d" font-size="3.2" font-weight="700">X0 Y152.4</text>','<text x="152.4" y="163" text-anchor="end" fill="#536b7d" font-size="3.2" font-weight="700">X152.4 Y152.4</text>','<text x="76.2" y="-12" text-anchor="middle" fill="#536b7d" font-size="2.8">X (mm)</text>','<text x="-14" y="76.2" text-anchor="middle" fill="#536b7d" font-size="2.8" transform="rotate(-90 -14 76.2)">Y (mm)</text>');
 if(inkSegments.length){const boxY=syy(maxY),boxHeight=Math.max(0.4,maxY-minY),boxWidth=Math.max(0.4,maxX-minX);svg.push('<rect id="printExtents" x="'+minX.toFixed(3)+'" y="'+boxY.toFixed(3)+'" width="'+boxWidth.toFixed(3)+'" height="'+boxHeight.toFixed(3)+'" fill="none" stroke="#e05b62" stroke-width="0.45" stroke-dasharray="2 1.5"/>')}
 for(const s of result.segments){if(s.homeTravel)continue;const color=s.ink?'#168b5a':'#8daecc';const dash=s.ink?'':' stroke-dasharray="1.4 1.2"';svg.push('<path d="M '+s.x1.toFixed(3)+' '+syy(s.y1).toFixed(3)+' L '+s.x2.toFixed(3)+' '+syy(s.y2).toFixed(3)+'" fill="none" stroke="'+color+'" stroke-width="'+(s.ink?'0.55':'0.25')+'"'+dash+' stroke-linecap="round"/>')}
 svg.push('</svg>');$('gcodePreview').innerHTML=svg.join('');
 const bounds=inkSegments.length?'Print X '+minX.toFixed(1)+'–'+maxX.toFixed(1)+' · Y '+syy(maxY).toFixed(1)+'–'+syy(minY).toFixed(1):'Print extents —';const inkWarning=result.moves&&result.drawMoves===0?' · No pen-down moves detected (air plot or missing Z-down commands)':'';$('gcodeStats').innerHTML='<span class="preview-stat">Moves '+result.moves+'</span><span class="preview-stat">Ink moves '+result.drawMoves+'</span><span class="preview-stat">Travel moves '+result.travelMoves+'</span><span class="preview-stat">'+bounds+'</span>'+(result.outOfBed?'<span class="preview-stat preview-warning">Outside bed '+result.outOfBed+'</span>':'<span class="preview-stat">All moves inside bed</span>')+(inkWarning?'<span class="preview-stat preview-warning">'+inkWarning+'</span>':'');
 $('gcodeMeta').textContent=text.trim()?'Parsed from the current G-code input.':'Paste or choose G-code to inspect its actual XY moves before storing it.';
}
let previewTimer=null;function schedulePreview(){clearTimeout(previewTimer);previewTimer=setTimeout(()=>renderGcodePreview($('jobText').value),80)}
$('jobText').addEventListener('input',schedulePreview);$('jobFile').addEventListener('change',async()=>{const file=$('jobFile').files[0];if(!file)return;const text=await file.text();$('jobText').value=text;renderGcodePreview(text)});
let dragState=null;
function dragStart(event){if(!$('jobText').value.trim())return;const rect=$('gcodePreview').getBoundingClientRect();dragState={startX:event.clientX,startY:event.clientY,baseX:Number($('offsetX').value)||0,baseY:Number($('offsetY').value)||0,width:rect.width,height:rect.height};$('gcodePreview').classList.add('dragging');if($('gcodePreview').setPointerCapture)$('gcodePreview').setPointerCapture(event.pointerId);event.preventDefault()}
function dragMove(event){if(!dragState)return;const dx=(event.clientX-dragState.startX)/dragState.width*BED.xmax,screenDy=(event.clientY-dragState.startY)/dragState.height*BED.ymax;$('offsetX').value=(dragState.baseX+dx).toFixed(1);$('offsetY').value=(dragState.baseY+screenDy).toFixed(1);const outline=document.getElementById('printExtents');if(outline)outline.setAttribute('transform','translate('+dx.toFixed(3)+' '+screenDy.toFixed(3)+')');event.preventDefault()}
function dragEnd(){if(!dragState)return;const moved=(Number($('offsetX').value)||0)!==dragState.baseX||(Number($('offsetY').value)||0)!==dragState.baseY;dragState=null;$('gcodePreview').classList.remove('dragging');if(moved)applyOffset();else renderGcodePreview($('jobText').value)}
$('gcodePreview').addEventListener('pointerdown',dragStart);$('gcodePreview').addEventListener('pointermove',dragMove);$('gcodePreview').addEventListener('pointerup',dragEnd);$('gcodePreview').addEventListener('pointercancel',dragEnd);
function resetOffset(){$('offsetX').value=0;$('offsetY').value=0;renderGcodePreview($('jobText').value)}
function applyOffset(){const dx=Number($('offsetX').value)||0,dy=Number($('offsetY').value)||0;if(!dx&&!dy){$('message').textContent='No offset entered.';return}if(/^\s*G91\b/im.test($('jobText').value)){$('message').textContent='Offset requires absolute G-code (G90).';return}$('jobText').value=$('jobText').value.split(/\r?\n/).map(source=>{const line=source.replace(/;.*$/,'');if(!/^\s*G[01]\b/i.test(line))return source;return source.replace(/([XY])\s*([-+]?\d*\.?\d+)/ig,(match,axis,value)=>axis.toUpperCase()+' '+(Number(value)+(axis.toUpperCase()==='X'?dx:-dy)).toFixed(3))}).join('\n');$('offsetX').value=0;$('offsetY').value=0;$('jobFile').value='';renderGcodePreview($('jobText').value);$('message').textContent='Offset applied to the G-code text. Validate and store it when ready.'}
$('offsetX').addEventListener('input',schedulePreview);$('offsetY').addEventListener('input',schedulePreview);
renderGcodePreview('');
async function request(url,options={}){const r=await fetch(url,options);const t=await r.text();let d={};try{d=JSON.parse(t)}catch{d={message:t}}if(!r.ok)throw new Error(d.error||d.message||('HTTP '+r.status));return d}
function formBody(values){const p=new URLSearchParams();Object.entries(values).forEach(([k,v])=>p.set(k,v));return p}
async function uploadDraft(){
 try{
  const text=$('jobText').value;const file=$('jobFile').files[0];
  if(!text.trim()&&!file)throw new Error('Choose a file or paste G-code.');
  const fd=new FormData();
  // The editor is authoritative: a selected file is only the initial load.
  fd.append('job',new Blob([text],{type:'text/plain'}),file?file.name:'draft.gcode');
  $('message').textContent='Saving edited draft…';await request('/api/job/draft',{method:'POST',body:fd});$('message').textContent='Draft saved. Review the preview, then validate the final job.';await poll();
 }catch(e){$('message').textContent=e.message}
}
async function validateFinalJob(){
 try{
  const text=$('jobText').value;if(!text.trim())throw new Error('Load or paste a G-code draft first.');const fd=new FormData();fd.append('job',new Blob([text],{type:'text/plain'}),'final.gcode');$('message').textContent='Validating final G-code…';await request('/api/job',{method:'POST',body:fd});$('message').textContent='Final G-code validated and stored. Use Start to plot it.';await poll();
 }catch(e){$('message').textContent='Final G-code rejected: '+e.message}
}
async function action(name){try{await request('/api/job/'+name,{method:'POST'});await poll()}catch(e){$('message').textContent=e.message}}
async function emergency(){if(!confirm('Send M112 immediately? The Printrboard may require reset.'))return;try{await request('/api/emergency',{method:'POST'});await poll()}catch(e){$('message').textContent=e.message}}
async function queryPrinter(command){try{await request('/api/printer/query',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:formBody({command})});$('message').textContent=command+' sent; inspect UART activity.'}catch(e){$('message').textContent=e.message}}
async function saveWifi(){try{await request('/api/wifi',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:formBody({ssid:$('ssid').value,password:$('password').value})});$('message').textContent='Saved. Bridge is restarting…'}catch(e){$('message').textContent=e.message}}
function cls(state){return ['failed','emergency'].includes(state)?'value bad':['paused','cancelling'].includes(state)?'value warn':['ready','running','completed'].includes(state)?'value good':'value'}
async function poll(){
 try{const s=await request('/api/status');latest=s;$('firmware').textContent=s.firmware;$('wifi').textContent=s.wifi_mode;$('ip').textContent=s.ip;$('printer').textContent=s.printer_connected?'responding':'no response yet';$('printer').className=s.printer_connected?'value good':'value warn';$('state').textContent=s.job.state;$('state').className=cls(s.job.state);$('commands').textContent=s.job.completed+' / '+s.job.total;$('bytes').textContent=Math.round(s.job.bytes/1024)+' KiB';$('active').textContent=s.job.active||'—';$('progress').value=s.job.progress;if(s.job.error)$('message').textContent=s.job.error;$('log').textContent=s.log.join('\n')||'No UART lines yet.';$('log').scrollTop=$('log').scrollHeight;
  $('start').disabled=s.job.state!=='ready'&&!['completed','cancelled','failed'].includes(s.job.state);$('pause').disabled=s.job.state!=='running';$('resume').disabled=s.job.state!=='paused';$('cancel').disabled=!['ready','running','paused'].includes(s.job.state);
 }catch(e){$('message').textContent='Bridge unavailable: '+e.message}
}
poll();setInterval(poll,1000);
</script>
</body></html>
)HTML";

}  // namespace plotter::web
