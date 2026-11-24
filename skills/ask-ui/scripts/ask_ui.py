#!/usr/bin/env python3
"""ask_ui.py - Human-in-the-loop UI for Claude Code. One browser tab, a thread of
cards Claude pushes (content + questions). CLI blocks until the user answers.

Commands:
  ask_ui.py ask  SPEC.json [--timeout SEC] [--no-open] [--quiet]   push, wait, print answer
  ask_ui.py show SPEC.json                                         push content only, return now
  ask_ui.py wait ID [--timeout SEC]                                keep waiting for an earlier ask
  ask_ui.py cancel ID                                              withdraw a card you pushed by mistake
  ask_ui.py status | list | stop | open      [--session ID]  (default session = $CLAUDE_CODE_SESSION_ID)

Each Claude Code session gets its own thread/tab at /t/<session>. '/' lists open threads.

Env: ASK_UI_KEEP_OPEN=1 keeps the tab open after the last pending question is answered
(default: the page closes its own tab once nothing is pending).

Spec (JSON):
{
  "title": "...", "why": "one line: why Claude asks", "intro": "html ok",
  "auto_submit": true|false,          # default: true when exactly one single/image question
  "submit_label": "보내기",
  "content": [                        # shown above the questions
    {"type":"markdown","text":"..."},
    {"type":"code","lang":"py","text":"..."},
    {"type":"diff","text":"unified diff"},
    {"type":"image","src":"/abs/path.png | https://... | data:","caption":"..."},
    {"type":"video","src":"/abs/path.mp4","caption":"...","loop":true},
    {"type":"html","text":"<raw html>"},                  # live, in an iframe
    {"type":"mermaid","text":"graph LR; a-->b"},
    {"type":"compare","items":[{"label":"A","image":"/p.png"},{"label":"B","html":"<...>"},{"label":"C","code":"..."}]}
  ],
  "questions": [
    {"id":"q1","type":"single","label":"...","desc":"...","required":true,"other":true,
     "options":[{"value":"a","label":"A","desc":"...","recommended":true},"b"]},
    {"id":"q2","type":"multi","label":"...","options":[...]},
    {"id":"q3","type":"scale","label":"...","min":1,"max":5,"min_label":"","max_label":"","default":3},
    {"id":"q4","type":"text","label":"...","placeholder":"","rows":3},
    {"id":"q5","type":"rank","label":"...","options":[...]},
    {"id":"q6","type":"image","label":"...","options":[{"value":"a","label":"A","img":"/p.png"},{"value":"b","label":"B","html":"<live html>"}]},
    {"id":"q7","type":"single","label":"...","show_if":{"q":"q1","eq":"a"}, ...}   # also "in":[..], "neq"
  ]
}

Output of ask/wait (stdout JSON):
  {"status":"submitted","id":..,"answers":{...},"elapsed_sec":..,"log":..}  exit 0
  {"status":"cancelled", ...}  exit 3        {"status":"timeout","id":..}  exit 2
  {"status":"error","error":..,"problems":[..]}  exit 1   (bad spec, or the page could not render the card)
Any of these may also carry:
  "late_answers":[{id,title,status,answers,asked_at,answered_at}]  answers to earlier cards that arrived after their
                                                                    ask timed out; delivered once, act on them first
  "warnings":[..]  spec keys the page ignores      "missing":[..]  local files that could not be shown
Answer values: "_pass" = the user chose 판단 불가 on a required question; "_note" = free text to Claude on any card.

File paths in a spec may be absolute, ~/..., or relative to the spec file (cwd when the spec comes from stdin).
Tests: python3 ../tests/test_ask_ui.py  (temp HOME, no browser). Bump VERSION when the page or daemon changes.
"""
import argparse
import html
import json
import os
import re
import select
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.expanduser("~/.claude/ask-ui")
HISTORY_DIR = os.path.join(BASE, "history")
STATE_FILE = os.path.join(BASE, "daemon.json")
LOCK_FILE = os.path.join(BASE, "daemon.lock")
THREAD_KEEP = 30
THREAD_MAX_AGE = 12 * 3600
# 아직 답이 없거나, 답은 왔는데 Claude 가 못 읽은 카드는 더 오래 둔다.
# 근거: 실측한 가장 늦은 답이 11.4시간. 주말을 넘겨 답하는 경우까지 덮도록 7일(내가 정한 값).
PENDING_MAX_AGE = 7 * 24 * 3600
EVENTS_FILE = os.path.join(BASE, "events.jsonl")
IDLE_EXIT_SEC = 3 * 3600
KEEP_OPEN = os.environ.get("ASK_UI_KEEP_OPEN", "") != ""
# 페이지나 데몬 동작이 바뀌면 올린다. CLI 와 다른 버전의 데몬은 대기 중인 질문이 없을 때 자동 교체된다.
VERSION = 3
PREFERRED_PORT = 47821

CLIENT_FRESH_SEC = 40

# ============================================================ page
CSS = r"""
:root{--bg:#f6f5f2;--card:#fff;--fg:#1b1b1b;--muted:#6b6b6b;--line:#e4e2dd;--acc:#2f5bea;--acc-bg:#eaf0ff;--ok:#1f8f4e;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--fg:#ececec;--muted:#9a9a9a;--line:#333;--acc:#7a9bff;--acc-bg:#232b45;--ok:#4cc27a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 120px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:16px;animation:in .25s ease-out}
@keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.card.done{opacity:.72}
.card.done .form,.card.done .content{display:none}
.card.done.open .content{display:block}
.card.done .ans{display:block;cursor:pointer}
.card.done .ans:hover{text-decoration:underline}
.ans{display:none;color:var(--muted);font-size:14px;margin-top:6px;white-space:pre-wrap;overflow-wrap:anywhere}
.card h1{font-size:20px;margin:0 0 4px;overflow-wrap:anywhere}
.why{color:var(--muted);font-size:13px;margin:0 0 10px}
.intro{margin:0 0 16px}
.ts{float:right;color:var(--muted);font-size:12px}
.blk{margin:0 0 16px}
.blk img,.blk video{max-width:100%;max-height:420px;object-fit:contain;border-radius:8px;border:1px solid var(--line);display:block;cursor:zoom-in}
.blk img.full{max-height:none;cursor:zoom-out}
.cmp img{max-height:300px}
.blk .cap{color:var(--muted);font-size:13px;margin-top:4px}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font:13px/1.45 var(--mono);margin:0}
.md pre{margin:8px 0}.md code{font:13px var(--mono);background:var(--bg);padding:1px 4px;border-radius:4px}.md pre code{background:none;padding:0}
.md table{border-collapse:collapse}.md td,.md th{border:1px solid var(--line);padding:4px 8px}
.diff .a{color:var(--ok)}.diff .d{color:#d33}.diff .h{color:var(--muted)}
iframe.live{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;min-height:120px}
.cmp{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.cmp>div{border:1px solid var(--line);border-radius:10px;padding:8px}
.cmp .lab{font-weight:600;font-size:14px;margin-bottom:6px}
.q{border-top:1px solid var(--line);padding-top:16px;margin-top:16px}
.q.hidden{display:none}
.q h2{font-size:16px;margin:0 0 4px;overflow-wrap:anywhere}
.q .desc{color:var(--muted);font-size:14px;margin:0 0 10px}
.req{color:#d33;margin-left:4px}
.opts{display:grid;gap:8px}
.opt{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer;background:transparent;color:inherit;text-align:left;font:inherit;width:100%;position:relative}
.opt:hover{border-color:var(--acc)}
.opt.on{border-color:var(--acc);background:var(--acc-bg)}
.opt .k{flex:none;width:22px;height:22px;border-radius:6px;border:1px solid var(--line);font-size:12px;display:flex;align-items:center;justify-content:center;color:var(--muted);margin-top:2px}
.opt.on .k{background:var(--acc);color:#fff;border-color:var(--acc)}
.opt .t{flex:1;min-width:0;overflow-wrap:anywhere}.opt .d{display:block;color:var(--muted);font-size:13px}
.badge{font-size:11px;color:var(--acc);border:1px solid var(--acc);border-radius:99px;padding:0 6px;margin-left:6px;vertical-align:middle}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.grid .opt{flex-direction:column;padding:8px}
.grid img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:6px;background:var(--line)}
.opt.neg{border-color:#e5484d;background:rgba(229,72,77,.12)}
.t-rate .grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}
.t-rate .opt.on::after,.t-rate .opt.neg::after{position:absolute;top:12px;left:12px;font-size:12px;font-weight:600;color:#fff;border-radius:6px;padding:2px 6px}
.t-rate .opt.on::after{content:attr(data-like);background:var(--acc)}.t-rate .opt.neg::after{content:attr(data-dislike);background:#e5484d}
.t-rate.m-reject .opt::before{display:none}
.notebox{border-top:1px solid var(--line);padding-top:16px;margin-top:16px}
.notebox textarea{display:block}.notebox.shut textarea{display:none}
.pass{background:none;border:0;color:var(--muted);font:inherit;font-size:13px;text-decoration:underline;text-underline-offset:3px;cursor:pointer;padding:8px 0 0}
.q.passed .opts,.q.passed .grid,.q.passed .scale,.q.passed textarea,.q.passed input[type=text]{opacity:.4}
.q.passed .pass{color:var(--acc);font-weight:600;text-decoration:none}
.t-rate .opt::before{content:"← " attr(data-dislike) " | " attr(data-like) " →";position:absolute;bottom:36px;left:50%;transform:translateX(-50%);font-size:11px;color:#fff;background:rgba(0,0,0,.6);padding:1px 6px;border-radius:6px;white-space:nowrap;opacity:0;transition:opacity .12s;pointer-events:none}
.t-rate .opt:hover::before{opacity:1}
.t-rate .cell{display:flex;flex-direction:column;min-width:0}.t-rate .cell .opt{flex:1}
.t-rate .detail{display:block;font-size:12px;padding:5px 2px 0;color:var(--acc);text-underline-offset:3px}
.grid iframe{width:100%;height:160px;border:1px solid var(--line);border-radius:6px;background:#fff;pointer-events:none}
input[type=text],textarea{width:100%;border:1px solid var(--line);border-radius:8px;padding:10px;font:inherit;background:transparent;color:inherit}
.other{margin-top:8px;display:none}.other.show{display:block}
.scale{display:flex;align-items:center;gap:12px}.scale input{flex:1}
.scale .lab{font-size:13px;color:var(--muted);min-width:40px;text-align:center}.scale .val{font-weight:600;min-width:28px;text-align:center}
.t-rank .opt .k{border-radius:50%}
.err{color:#d33;font-size:13px;margin-top:8px;display:none}
.actions{display:flex;gap:10px;align-items:center;margin-top:18px;flex-wrap:wrap}
.actions .hint{color:var(--muted);font-size:13px;flex:1;min-width:120px}
button.primary{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:10px 20px;font:inherit;font-weight:600;cursor:pointer}
button.ghost{background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:10px;padding:10px 14px;font:inherit;cursor:pointer}
#status{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;font-size:13px;color:var(--muted);text-align:center}
#status.off{color:#d33}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ok);margin-right:6px;animation:pulse 1.6s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
"""

JS = r"""
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm=o=>(o&&typeof o==='object')?Object.assign({label:o.value},o):{value:o,label:String(o)};
const src=s=>(s&&s.startsWith('/')&&!s.startsWith('//'))?'/file?p='+encodeURIComponent(s):s;
const SID=location.pathname.startsWith('/t/')?decodeURIComponent(location.pathname.slice(3)):'default';
const SQ='&s='+encodeURIComponent(SID); let LABEL='', EPOCH=null, KEEP=false; const PAGE_V=0;
let seq=0, pendingCount=0; const states={};
const libs={};
function lib(name,url){return libs[name]||(libs[name]=new Promise((res,rej)=>{const s=document.createElement('script');s.src=url;s.onload=res;s.onerror=rej;document.head.appendChild(s);}));}

function block(b){try{return block0(b||{});}catch(e){return `<div class="blk"><pre>블록 렌더 실패(${esc(b&&b.type)}): ${esc(e.message)}</pre></div>`;}}
function block0(b){
  const cap=b.caption?`<div class="cap">${esc(b.caption)}</div>`:'';
  switch(b.type){
    case 'markdown': return `<div class="blk md" data-md>${`<pre>${esc(b.text)}</pre>`}</div>`;
    case 'code': return `<div class="blk"><pre>${esc(b.text)}</pre>${cap}</div>`;
    case 'diff': return `<div class="blk diff"><pre>${String(b.text??'').split('\n').map(l=>`<span class="${l.startsWith('+')?'a':l.startsWith('-')?'d':/^(@@|diff|index)/.test(l)?'h':''}">${esc(l)}</span>`).join('\n')}</pre>${cap}</div>`;
    case 'image': return `<div class="blk"><img src="${esc(src(b.src))}" alt="">${cap}</div>`;
    case 'video': return `<div class="blk"><video src="${esc(src(b.src))}" controls autoplay muted playsinline ${b.loop!==false?'loop':''}></video>${cap}</div>`;
    case 'html': return `<div class="blk"><iframe class="live" sandbox="allow-scripts" srcdoc="${esc(b.text)}" style="height:${b.height||240}px"></iframe>${cap}</div>`;
    case 'mermaid': return `<div class="blk" data-mermaid><pre class="mermaid">${esc(b.text)}</pre>${cap}</div>`;
    case 'compare': return `<div class="blk cmp">${(b.items||[]).map(it=>`<div><div class="lab">${esc(it.label||'')}</div>${it.image?`<img src="${esc(src(it.image))}" alt="">`:''}${it.html?`<iframe class="live" sandbox="allow-scripts" srcdoc="${esc(it.html)}" style="height:${it.height||200}px"></iframe>`:''}${it.code?`<pre>${esc(it.code)}</pre>`:''}${it.text?`<div>${esc(it.text)}</div>`:''}</div>`).join('')}</div>`;
    default: return `<div class="blk"><pre>${esc(JSON.stringify(b))}</pre></div>`;
  }
}
async function enhance(card,item){
  // markdown 과 intro 는 걸러서 넣는다: Claude 가 옮겨 온 바깥 글에 스크립트가 섞여 있어도 실행되지 않는다.
  // 라이브러리를 못 받으면(오프라인) 글자 그대로 보인다.
  if($('[data-md],[data-intro]',card)){
    try{await lib('purify','https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js');
      const it=$('[data-intro]',card);if(it)it.innerHTML=DOMPurify.sanitize(item.intro);
      if($('[data-md]',card)){await lib('marked','https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js');
        $$('[data-md]',card).forEach((el,i)=>{const b=item.content.filter(x=>x&&x.type==='markdown')[i];el.innerHTML=DOMPurify.sanitize(marked.parse(String(b.text??'')));});}
    }catch(e){}
  }
  if($('[data-mermaid]',card)){
    try{await lib('mermaid','https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js');
      mermaid.initialize({startOnLoad:false,theme:matchMedia('(prefers-color-scheme:dark)').matches?'dark':'default'});
      await mermaid.run({nodes:$$('.mermaid',card)});}catch(e){}
  }
}
function question(q){
  const opts=(q.options||[]).map(norm);
  let h=`<section class="q t-${q.type}" data-id="${esc(q.id)}"><h2>${esc(q.label)}${q.required?'<span class="req">*</span>':''}</h2>`;
  if(q.desc) h+=`<p class="desc">${esc(q.desc)}</p>`;
  const RL=rateLabels(q);
  const optBtn=(o,i,inner)=>`<button type="button" class="opt${o.recommended&&q.type!=='rank'&&q.mode!=='reject'?' on':''}" data-v="${esc(o.value)}"${q.type==='rate'?` data-like="${esc(RL.like)}" data-dislike="${esc(RL.dislike)}"`:''}>${inner}</button>`;
  if(q.type==='rate'&&q.mode==='reject'){h=h.replace('class="q t-rate"','class="q t-rate m-reject"');h+=`<p class="desc" data-ratehint></p>`;}
  const txt=o=>`<span class="t">${esc(o.label)}${o.recommended?'<span class="badge">추천</span>':''}${o.desc?`<span class="d">${esc(o.desc)}</span>`:''}</span>`;
  // multi 옵션에 img/html 이 있으면 이미지 그리드로 다중 선택. q.aspect 로 이미지 비율 지정(기본 4/3, 세로 사진은 "3/4")
  // rate: 이미지 그리드, 클릭할 때마다 없음 → 좋음 → 싫음 → 없음. 답은 {like:[], dislike:[]}
  // rate 옵션에 url 이 있으면 칸 아래에 '상세 보기' 링크(버튼 안에는 링크를 넣을 수 없어 바깥에 둔다)
  if(q.type==='rate'&&opts.some(o=>o.url)){
    h+=`<div class="grid">`+opts.map((o,i)=>`<div class="cell">`+optBtn(o,i,`<img src="${esc(src(o.img))}" alt=""${q.aspect?` style="aspect-ratio:${esc(q.aspect)}"`:''}>`+txt(o))+(o.url?`<a class="detail" href="${esc(o.url)}" target="_blank" rel="noopener">상세 보기</a>`:'')+`</div>`).join('')+`</div>`;
  } else if(q.type==='image'||q.type==='rate'||(q.type==='multi'&&opts.some(o=>o.img||o.html))){
    h+=`<div class="grid">`+opts.map((o,i)=>optBtn(o,i,(o.html?`<iframe sandbox="allow-scripts" srcdoc="${esc(o.html)}"></iframe>`:`<img src="${esc(src(o.img))}" alt=""${q.aspect?` style="aspect-ratio:${esc(q.aspect)}"`:''}>`)+txt(o))).join('')+`</div>`;
  } else if(q.type==='single'||q.type==='multi'){
    h+=`<div class="opts">`+opts.map((o,i)=>optBtn(o,i,`<span class="k">${i+1}</span>`+txt(o))).join('')+`</div>`;
    if(q.other) h+=`<button type="button" class="ghost" style="margin-top:8px" data-other>기타…</button><div class="other"><input type="text" placeholder="${esc(q.other_placeholder||'직접 입력')}"></div>`;
  } else if(q.type==='scale'){
    const mn=q.min??1,mx=q.max??5,df=q.default??Math.round((mn+mx)/2);
    h+=`<div class="scale"><span class="lab">${esc(q.min_label||mn)}</span><input type="range" min="${mn}" max="${mx}" step="${q.step||1}" value="${df}"><span class="lab">${esc(q.max_label||mx)}</span><span class="val">${df}</span></div>`;
  } else if(q.type==='text'){
    h+=(q.rows&&q.rows>1)?`<textarea rows="${q.rows}" placeholder="${esc(q.placeholder||'')}"></textarea>`:`<input type="text" placeholder="${esc(q.placeholder||'')}">`;
  } else if(q.type==='rank'){
    h+=`<p class="desc" data-rankhint>클릭 순서 = 순위. 다시 클릭하면 취소. (0/${opts.length})</p><div class="opts">`+opts.map(o=>optBtn(o,0,`<span class="k"></span>`+txt(o))).join('')+`</div>`;
  }
  // 필수 질문에서 억지로 고르지 않게 하는 출구. 답 값은 '_pass'
  if(q.required) h+=`<button type="button" class="pass" data-pass>판단 불가</button>`;
  return h+`<div class="err">필수 항목입니다.</div></section>`;
}
// rate 배지 글자. mode:"reject" 는 한 번 누르면 제외만 표시한다
function rateLabels(q){const l=q.labels||{};return {like:l.like||'좋음',dislike:l.dislike||(q.mode==='reject'?'제외':'싫음')};}
function rateHint(sec,q){const h=$('[data-ratehint]',sec);if(h)h.textContent=`누르면 ${rateLabels(q).dislike} · 다시 누르면 취소 (${$$('.opt.neg',sec).length}/${$$('.opt',sec).length})`;}

// 다른 카드에 답하는 중이면 새 카드가 초점과 스크롤을 가져가지 않는다
function busy(card){const a=document.activeElement,f=a&&a.closest&&a.closest('.card:not(.done) .form');return !!(f&&!card.contains(f));}
// 카드가 막 뜨거나 창이 막 앞으로 나온 직후의 Enter/숫자키는 터미널에 치던 입력일 수 있어 0.5초간 받지 않는다
let armAt=0; addEventListener('focus',()=>{armAt=Math.max(armAt,performance.now()+500);});
function isAuto(item){
  if(item.auto_submit!=null) return !!item.auto_submit;
  const qs=item.questions||[]; return qs.length===1&&['single','image'].includes(qs[0].type)&&!qs[0].other;
}
function render(item){
  const card=document.createElement('div'); card.className='card'; card.id='item-'+item.id;
  const qs=item.questions||[];
  let h=`<span class="ts">${new Date(item.ts*1000).toLocaleTimeString()}</span>`;
  if(item.title) h+=`<h1>${esc(item.title)}</h1>`;
  if(item.why) h+=`<p class="why">${esc(item.why)}</p>`;
  if(item.intro) h+=`<div class="intro" data-intro>${esc(item.intro)}</div>`;
  h+=`<div class="content">${(item.content||[]).map(block).join('')}</div>`;
  if(qs.length){
    // 카드마다 'Claude에게 한마디' 칸. 스펙에 "note":false 이거나 이미 id 가 note 인 질문이 있으면 넣지 않는다.
    // 클릭 = 전송인 카드에서는 접어 두고, 펼치면 자동 전송을 끈다.
    const noteOn=item.note!==false&&!qs.some(q=>q.id==='note'||q.id==='_note');
    const noteBox=!noteOn?'':isAuto(item)?`<div class="notebox shut"><button type="button" class="ghost" data-noteopen>한마디 남기기</button><textarea rows="2" data-note placeholder="Claude에게 한마디 (선택)"></textarea></div>`:`<div class="notebox"><textarea rows="2" data-note placeholder="Claude에게 한마디 (선택)"></textarea></div>`;
    h+=`<div class="form">${qs.map(question).join('')}${noteBox}<div class="actions"><span class="hint">${isAuto(item)?'클릭하면 바로 전송':'숫자키 선택 · Enter 전송'}</span><button type="button" class="ghost" data-skip>건너뛰기</button><button type="button" class="primary" data-submit>${esc(item.submit_label||'보내기')}</button></div></div>`;
  }
  h+=`<div class="ans"></div>`;
  card.innerHTML=h; $('#thread').appendChild(card);
  enhance(card,item);
  if(qs.length&&!item.done){bind(card,item);pendingCount++;setStatus();}
  else if(qs.length&&item.done){markDone(card,item,item.answer?.status==='lost'?'expired':(item.answer?.status||'submitted'),item.answer?.answers||{});}
  $$('.blk img',card).forEach(im=>im.onclick=()=>im.classList.toggle('full'));
  $('.ans',card).onclick=()=>card.classList.toggle('open');
  if(!busy(card))card.scrollIntoView({behavior:'smooth',block:'start'});
  return card;
}
function bind(card,item){
  const st=states[item.id]={}; const auto=isAuto(item);
  (item.questions||[]).forEach(q=>{ if(q.type==='scale'){st[q.id]=q.default??Math.round(((q.min??1)+(q.max??5))/2);} if(q.type==='rank')st[q.id]=[]; if(q.type==='rate')st[q.id]={like:[],dislike:[]};
    const rec=(q.options||[]).map(norm).filter(o=>o.recommended).map(o=>o.value); if(rec.length&&q.type!=='rank'&&!(q.type==='rate'&&q.mode==='reject')){st[q.id]=q.type==='multi'?rec:q.type==='rate'?{like:rec,dislike:[]}:rec[0];} });
  const update=()=>applyShowIf(card,item,st);
  $$('section.q',card).forEach(sec=>{
    const id=sec.dataset.id,q=item.questions.find(x=>x.id===id);
    const CTL='.opt,[data-other],input,textarea';
    sec.addEventListener('click',e=>{if(e.target.closest&&e.target.closest('.opt,[data-other]'))sec.dataset.touched=1;});
    // '판단 불가' 를 누른 뒤 다시 답하기 시작하면 원래 상태로 되돌린다(옵션 핸들러보다 먼저 돌도록 capture)
    // 화면의 선택·입력은 건드리지 않는다(흐리게만). 누르기 전 답을 간직했다가 그대로 돌려준다
    let prev;
    const unpass=e=>{if(!(e.target.closest&&e.target.closest(CTL)))return;if(sec.classList.contains('passed')){sec.classList.remove('passed');st[id]=prev;update();}};
    sec.addEventListener('click',unpass,true);sec.addEventListener('input',unpass,true);
    const pb=$('[data-pass]',sec);
    if(pb)pb.onclick=()=>{const on=!sec.classList.contains('passed');sec.classList.toggle('passed',on);
      if(on){prev=st[id];st[id]='_pass';}else st[id]=prev;
      update();if(on&&auto&&!card.dataset.noauto)setTimeout(()=>submit(card,item,'submitted'),180);};
    const oth=()=>{const i=$('.other.show input',sec);return i&&i.value?['other:'+i.value]:[];};
    if(q.type==='single'||q.type==='image'){
      $$('.opt',sec).forEach(b=>b.onclick=()=>{$$('.opt',sec).forEach(x=>x.classList.remove('on'));b.classList.add('on');st[id]=b.dataset.v;$('.other',sec)?.classList.remove('show');update();if(auto&&!card.dataset.noauto)setTimeout(()=>submit(card,item,'submitted'),180);});
    } else if(q.type==='multi'){
      $$('.opt',sec).forEach(b=>b.onclick=()=>{b.classList.toggle('on');st[id]=$$('.opt.on',sec).map(x=>x.dataset.v).concat(oth());update();});
    } else if(q.type==='rate'){
      // 기본: 오른쪽 절반 클릭 = 좋음, 왼쪽 절반 = 싫음. 같은 쪽을 다시 누르면 해제.
      // mode:"reject": 어디를 눌러도 제외 표시만 켰다 끈다(나쁜 것만 걸러내는 카드).
      // 키보드(Tab 으로 가서 Space/Enter, e.detail===0)는 위치가 없으므로 없음 → 좋음 → 싫음 → 없음 순으로 돈다.
      $$('.opt',sec).forEach(b=>b.onclick=e=>{
        if(q.mode==='reject'){b.classList.remove('on');b.classList.toggle('neg');}
        else if(e.detail===0){const was=b.classList.contains('on')?1:b.classList.contains('neg')?2:0;b.classList.remove('on','neg');if(was===0)b.classList.add('on');if(was===1)b.classList.add('neg');}
        else{const r=b.getBoundingClientRect(),like=e.clientX>r.left+r.width/2;b.classList.remove(like?'neg':'on');b.classList.toggle(like?'on':'neg');}
        st[id]={like:$$('.opt.on',sec).map(x=>x.dataset.v),dislike:$$('.opt.neg',sec).map(x=>x.dataset.v)};rateHint(sec,q);update();});
      rateHint(sec,q);
    } else if(q.type==='scale'){
      const r=$('input[type=range]',sec),v=$('.val',sec);r.oninput=()=>{v.textContent=r.value;st[id]=Number(r.value);update();};
    } else if(q.type==='text'){
      const t=$('textarea,input',sec);t.oninput=()=>{st[id]=t.value;update();};
    } else if(q.type==='rank'){
      $$('.opt',sec).forEach(b=>b.onclick=()=>{const v=b.dataset.v,a=st[id],i=a.indexOf(v);if(i>=0)a.splice(i,1);else a.push(v);$$('.opt',sec).forEach(x=>{const j=a.indexOf(x.dataset.v);x.classList.toggle('on',j>=0);$('.k',x).textContent=j>=0?j+1:'';});const hh=$('[data-rankhint]',sec);if(hh)hh.textContent=`클릭 순서 = 순위. 다시 클릭하면 취소. (${a.length}/${$$('.opt',sec).length})`;update();});
    }
    const ob=$('[data-other]',sec);
    if(ob){const box=$('.other',sec),inp=$('input',box);ob.onclick=()=>{box.classList.add('show');inp.focus();if(q.type!=='multi'){$$('.opt',sec).forEach(x=>x.classList.remove('on'));st[id]='other:'+inp.value;}else{st[id]=$$('.opt.on',sec).map(x=>x.dataset.v).concat(oth());}update();};
      inp.oninput=()=>{st[id]=q.type==='multi'?$$('.opt.on',sec).map(x=>x.dataset.v).concat(oth()):'other:'+inp.value;update();};}
  });
  update();
  const no=$('[data-noteopen]',card);
  if(no)no.onclick=()=>{card.dataset.noauto=1;no.parentNode.classList.remove('shut');no.style.display='none';$('.hint',card).textContent='숫자키 선택 · Enter 전송';$('[data-note]',card).focus();};
  $('[data-submit]',card).onclick=()=>submit(card,item,'submitted');
  $('[data-skip]',card).onclick=()=>submit(card,item,'cancelled');
  card.addEventListener('input',()=>{card.dataset.dirty=1;});
  card.addEventListener('click',e=>{if(e.target.closest&&e.target.closest('.opt,[data-pass]'))card.dataset.dirty=1;});
  card.onkeydown=e=>{
    // 한글 조합 중 Enter 는 글자 확정이지 제출이 아니다
    if(e.isComposing||e.keyCode===229)return;
    const tg=e.target, field=!!(tg.matches&&tg.matches('input,textarea'));
    if(!field&&performance.now()<armAt&&(e.key==='Enter'||/^[0-9]$/.test(e.key)))return;
    if(e.key==='Enter'){
      if(tg.tagName==='TEXTAREA'&&!(e.metaKey||e.ctrlKey))return;
      if(tg.matches&&tg.matches('a,[data-skip],[data-other],[data-pass],[data-noteopen],.t-rate .opt'))return;
      e.preventDefault();submit(card,item,'submitted');return;}
    if(field||e.metaKey||e.ctrlKey||e.altKey)return;
    const n=parseInt(e.key);if(!n)return;
    const sec=$$('section.q:not(.hidden)',card).find(s=>{const q=item.questions.find(x=>x.id===s.dataset.id);return ['single','multi','image'].includes(q.type)&&(q.type==='multi'||!s.dataset.touched)});
    if(sec){const b=$$('.opt',sec)[n-1];if(b)b.click();}
  };
  card.tabIndex=-1; if(!busy(card))card.focus({preventScroll:true});
  armAt=Math.max(armAt,performance.now()+500);
}
function visible(q,st,qs,depth=0){const c=q.show_if;if(!c)return true;
  const par=(qs||[]).find(x=>x.id===c.q);if(par&&par!==q&&depth<20&&!visible(par,st,qs,depth+1))return false;
  const v=st[c.q]==='_pass'?undefined:st[c.q];const same=(a,b)=>a!=null&&String(a)===String(b);const has=x=>Array.isArray(v)?v.some(y=>same(y,x)):same(v,x);
  if('eq' in c)return has(c.eq); if('neq' in c)return !has(c.neq); if('in' in c)return c.in.some(has); if('truthy' in c)return !!v&&!(Array.isArray(v)&&!v.length); return true;}
function applyShowIf(card,item,st){item.questions.forEach(q=>{$(`section.q[data-id="${CSS.escape(q.id)}"]`,card).classList.toggle('hidden',!visible(q,st,item.questions));});}
function validate(card,item,st){let ok=true;item.questions.forEach(q=>{const sec=$(`section.q[data-id="${CSS.escape(q.id)}"]`,card),err=$('.err',sec);
  const v=st[q.id],empty=v==null||v===''||v==='other:'||(Array.isArray(v)&&!v.length)||(!!v&&Array.isArray(v.like)&&!v.like.length&&!(v.dislike||[]).length);const bad=q.required&&empty&&!(q.type==='rate'&&q.mode==='reject')&&visible(q,st,item.questions);err.style.display=bad?'block':'none';if(bad)ok=false;});return ok;}
async function submit(card,item,status){
  if(card.classList.contains('done'))return;
  const st=states[item.id];
  if(status==='submitted'&&!validate(card,item,st)){$('.err[style*=block]',card).scrollIntoView({behavior:'smooth',block:'center'});return;}
  const answers={};item.questions.forEach(q=>{if(visible(q,st,item.questions)&&st[q.id]!=null)answers[q.id]=st[q.id];});
  const note=($('[data-note]',card)?.value||'').trim();if(note)answers._note=note;
  if(card.dataset.sending)return; card.dataset.sending=1;
  // 데몬이 받았다고 답한 뒤에만 완료 처리한다. 실패하면 고른 답을 그대로 둔다
  let res=null;
  try{const r=await fetch('/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({session:SID,id:item.id,status,answers,diag:{history:history.length,hidden:document.hidden}})});if(r.ok)res=await r.json();}catch(e){}
  delete card.dataset.sending;
  const hint=$('.hint',card);
  if(!res){if(hint){hint.style.color='#d33';hint.textContent='전송 실패 · 답은 그대로 있습니다. 다시 눌러 주세요';}return;}
  markDone(card,item,res.ok?status:'expired',answers);pendingCount--;setStatus();
  const nx=$$('.card:not(.done)').find(x=>$('.form',x));if(nx)nx.focus({preventScroll:true});
  // 기다리는 CLI 가 없으면(타임아웃 뒤 늦은 답) 답은 저장되고 Claude 의 다음 호출에 실려 간다
  const sent=res.waiting===false?'✓ 저장됨 · Claude 가 다음 작업 때 읽습니다':'✓ 전달됨';
  if(pendingCount===0&&res.ok){if(KEEP){$('#status').textContent=sent;}else{$('#status').textContent=sent+' · 탭을 닫습니다';setTimeout(()=>{try{window.close()}catch(e){}},150);}}
}
function fmtAns(q,v){
  if(v==='_pass')return '판단 불가';
  if(q&&q.type==='rate'&&v&&typeof v==='object'){const L=rateLabels(q),a=(v.like||[]).length,b=(v.dislike||[]).length;return q.mode==='reject'?`${L.dislike} ${b}`:`${L.like} ${a} / ${L.dislike} ${b}`;}
  const lab=x=>{if(typeof x==='string'&&x.startsWith('other:'))return x.slice(6);const o=((q&&q.options)||[]).map(norm).find(o=>String(o.value)===String(x));return o?o.label:x;};
  if(v&&typeof v==='object'&&!Array.isArray(v))return Object.entries(v).map(([k,a])=>`${({like:'좋음',dislike:'싫음'})[k]||k} ${Array.isArray(a)?a.length:a}`).join(' / ');
  return Array.isArray(v)?v.map(lab).join(', '):lab(v);
}
function markDone(card,item,status,answers){card.classList.add('done');
  const head={submitted:'✓ ',cancelled:'건너뜀 ',expired:'닫힌 질문(전달 안 됨) ',error:'표시 실패 '}[status]??'';
  const qs=item.questions||[], many=Object.keys(answers).length>1;
  $('.ans',card).textContent=head+Object.entries(answers).map(([k,v])=>{const q=qs.find(x=>x.id===k),l=k==='_note'?'한마디':String((q&&q.label)||k);return (many?(l.length>18?l.slice(0,18)+'…':l)+': ':'')+fmtAns(q,v);}).join('  ·  ')+'  (펼치기)';}
function setStatus(){const s=$('#status');s.className='';s.innerHTML=pendingCount>0?`<span class="dot" style="background:#e0a800"></span>답을 기다리는 중 (${pendingCount})`:`<span class="dot"></span>Claude 작업 중 · 다음 질문이 오면 여기 표시됩니다`;document.title=(pendingCount>0?'● ':'')+(LABEL||'ask-ui');}
async function poll(){
  let quick=false;  // 끊겼다 붙은 직후에는 기다리지 않고 바로 상태를 받아 온다
  while(true){
    try{const r=await fetch('/events?since='+seq+'&wait='+(quick?0:25)+SQ);if(!r.ok)throw 0;const j=await r.json();quick=false;if(j.label&&j.label!==LABEL){LABEL=j.label;$('#label').textContent=LABEL;setStatus();}
      KEEP=!!j.keep;
      if(j.version!=null&&j.version!==PAGE_V&&!$$('.card:not(.done)').some(c=>c.dataset.dirty)){location.reload();return;}  // 답을 쓰던 중이면 보낸 뒤로 미룬다  // 데몬이 새 버전으로 바뀌면 페이지도 새로 받는다
      // 데몬 쪽 스레드가 새로 시작됐으면(stop, 만료) 번호가 다시 1부터라 화면을 새로 그린다
      if(EPOCH!=null&&j.epoch!==EPOCH){location.reload();return;} EPOCH=j.epoch;
      if($('#status').className==='off')setStatus();  // 다시 연결됨
      // 데몬에서 이미 끝난 질문(데몬 재시작, 다른 탭에서 답함)은 화면에서도 닫는다
      if(j.open)$$('.card:not(.done)').forEach(c=>{const id=Number(c.id.slice(5));if(states[id]&&!c.dataset.sending&&!j.open.includes(id)){markDone(c,{questions:[]},'expired',{});pendingCount--;setStatus();}});
      if(!j.items.length&&j.seq===seq){continue;}
      for(const it of j.items){seq=Math.max(seq,it.seq);if(!$('#item-'+it.id)){try{render(it);}catch(e){renderFail(it,e);}}}
      if(j.items.some(i=>(i.questions||[]).length&&!i.done)&&document.hidden){document.title='● 질문 도착 — Claude';}
    }catch(e){quick=true;const s=$('#status');s.className='off';s.textContent='연결 끊김 · 다음 질문이 오면 이 탭이 다시 연결됩니다';await new Promise(r=>setTimeout(r,2000));}
  }
}
function renderFail(it,e){
  // 카드를 못 그리면 조용히 멈추지 않고 CLI 에 바로 알려 Claude 가 스펙을 고치게 한다
  const old=$('#item-'+it.id); if(old)old.replaceWith();  // 그리다 만 카드는 치운다 (pendingCount 는 bind 가 끝나야 올라가므로 건드리지 않는다)
  const c=document.createElement('div');c.className='card';c.id='item-'+it.id;
  c.innerHTML=`<h1>${esc(it.title||'카드')}</h1><p class="why">이 카드를 표시하지 못했습니다. Claude 에게 오류를 전달했습니다.</p><pre>${esc(String(e&&e.stack||e))}</pre>`;
  $('#thread').appendChild(c);
  if((it.questions||[]).length&&!it.done)fetch('/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({session:SID,id:it.id,status:'error',answers:{},error:'render failed: '+String(e&&e.message||e)})}).catch(()=>{});
}
addEventListener('keydown',e=>{if(e.target!==document.body)return;const c=$$('.card:not(.done)').filter(x=>$('.form',x)).pop();if(c&&c.onkeydown)c.onkeydown(e);});
setStatus();poll();
addEventListener('pagehide',()=>{try{navigator.sendBeacon('/bye',JSON.stringify({session:SID}))}catch(e){}});
"""

PAGE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="same-origin"><title>Claude ask-ui</title><link rel="icon" href="data:,"><style>%s</style></head>
<body><main><div id="label" style="color:var(--muted);font-size:12px;margin-bottom:8px"></div><div id="thread"></div></main><div id="status"></div><script>%s</script></body></html>""" % (CSS, JS.replace("PAGE_V=0;", "PAGE_V=%d;" % VERSION))


# ============================================================ daemon
THREADS_DIR = os.path.join(BASE, "threads")


def safe_sid(sid):
    return re.sub(r"[^A-Za-z0-9._-]", "_", sid or "default")[:80] or "default"


def is_open(i):
    """Not answered yet, or answered but not yet handed to Claude."""
    return not i.get("done") or bool(i.get("answer") and not i.get("consumed", True))


def trim(items):
    old = [i for i in items if not is_open(i)][:-THREAD_KEEP]
    return [i for i in items if not any(i is o for o in old)] if old else list(items)


class Thread:
    def __init__(self, sid, cv):
        self.sid = sid
        self.cv = cv
        self.label = sid[:8]
        self.items = []
        self.seq = 0
        self.last_client = 0.0
        self.active = 0
        self.tab_gone = True
        self.last_push = time.time()
        self.files = set()
        self.keep = KEEP_OPEN
        self.delivered = 0  # 페이지가 실제로 받아 간 마지막 카드 번호
        self.epoch = time.time()  # 스레드가 처음 만들어진 때. 페이지가 번호 초기화를 알아채는 데 쓴다
        self.load()

    @property
    def path(self):
        return os.path.join(THREADS_DIR, self.sid + ".json")

    def load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except Exception:
            return
        now = time.time()
        def keep(i):
            age = now - i.get("ts", 0)
            open_ = not i.get("done") or (i.get("answer") and not i.get("consumed", True))
            return age < THREAD_MAX_AGE or (open_ and age < PENDING_MAX_AGE)
        items = trim([i for i in data.get("items", []) if keep(i)])
        # 답이 CLI 타임아웃 뒤 한참 있다 오는 일이 많아(이력 82건 중 14건), 대기 중인 질문은 데몬이 바뀌어도
        # 그대로 살려 둔다. 열려 있던 탭에서 계속 답할 수 있고 `wait <id>` 로 이어 받는다.
        for i in items:
            if i.get("done"):
                i.setdefault("consumed", True)  # 예전 버전이 남긴 답은 이미 읽은 것으로 본다
            self.files |= collect_paths(i)
        self.items = items
        self.seq = max([i["seq"] for i in items] + [data.get("seq") or 0])  # 카드가 다 지워져도 번호는 이어 간다
        self.label = data.get("label") or self.label
        self.epoch = data.get("epoch") or self.epoch

    def save(self):
        try:
            os.makedirs(THREADS_DIR, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"label": self.label, "epoch": self.epoch, "seq": self.seq, "items": trim(self.items)}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def pending(self):
        return sum(1 for i in self.items if not i["done"])

    def unread(self):
        """Answered cards whose answer no CLI has returned to Claude yet."""
        return [i for i in self.items if i.get("answer") and not i.get("consumed")]

    def has_client(self):
        return (not self.tab_gone) and (self.active > 0 or time.time() - self.last_client < CLIENT_FRESH_SEC)


class Daemon:
    def __init__(self):
        self.port = 0
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.threads = {}
        self.last_activity = time.time()
        self.waiting = 0  # 지금 답을 기다리며 멈춰 있는 CLI 수
        self.waiting_on = {}  # (세션, 카드 id) -> 그 카드를 기다리는 CLI 들의 '아직 붙어 있나' 함수
        self.prune()

    def prune(self):
        try:
            now = time.time()
            for fn in os.listdir(THREADS_DIR):
                fp = os.path.join(THREADS_DIR, fn)
                if fn.endswith(".json") and now - os.path.getmtime(fp) > PENDING_MAX_AGE:
                    os.remove(fp)
        except Exception:
            pass

    def get(self, sid, create=True):
        sid = safe_sid(sid)
        t = self.threads.get(sid)
        if t is None and (create or os.path.exists(os.path.join(THREADS_DIR, sid + ".json"))):
            t = self.threads[sid] = Thread(sid, self.cv)
        return t

    def push(self, sid, spec, label=None, keep=None):
        with self.cv:
            t = self.get(sid)
            if label:
                t.label = label
            if keep is not None:
                t.keep = bool(keep)
            t.seq += 1
            item = dict(spec)
            item.update(seq=t.seq, id=t.seq, ts=time.time(), done=not spec.get("questions"), answer=None)
            t.items.append(item)
            t.last_push = self.last_activity = time.time()
            t.files |= collect_paths(spec)
            t.save()
            log_event("push", session=t.sid, id=item["id"], questions=len(spec.get("questions") or []))
            self.cv.notify_all()
            return item["id"]

    def events(self, sid, since, wait):
        with self.cv:
            t = self.get(sid)
            t.last_client = self.last_activity = time.time()
            t.tab_gone = False
            t.active += 1
            try:
                end = time.time() + wait
                while True:
                    out = [i for i in t.items if i["seq"] > since]
                    if out or time.time() >= end:
                        if out and out[-1]["seq"] > t.delivered:
                            log_event("seen", session=t.sid, ids=[i["id"] for i in out if i["seq"] > t.delivered])
                            t.delivered = out[-1]["seq"]
                        return {"seq": t.seq, "items": out, "label": t.label, "epoch": t.epoch, "keep": t.keep, "version": VERSION,
                                "open": [i["id"] for i in t.items if not i["done"]]}
                    self.cv.wait(max(0.0, end - time.time()))
            finally:
                t.active -= 1

    def bye(self, sid):
        with self.cv:
            t = self.get(sid, create=False)
            if t:
                t.tab_gone = True

    def answer(self, sid, id_, status, answers, diag=None, error=None):
        with self.cv:
            t = self.get(sid, create=False)
            if not t:
                return False, False
            for i in t.items:
                if i["id"] == id_ and not i["done"]:
                    waiting = any(a is None or a() for a in self.waiting_on.get((t.sid, id_), []))
                    by_caller = isinstance(diag, dict) and diag.get("by") == "caller"
                    i["done"] = True
                    i["answer"] = {"status": status, "answers": answers, "answered_at": time.time(), "diag": diag}
                    # 기다리던 CLI 가 받아 가면 consume() 이 True 로 바꾼다. Claude 가 직접 철회한 카드는 알릴 필요가 없다.
                    i["consumed"] = by_caller
                    log_event("answer", session=t.sid, id=id_, status="withdrawn" if by_caller else status,
                              late=not waiting and not by_caller,
                              sec=round(time.time() - i.get("ts", time.time())))
                    if error:
                        i["answer"]["error"] = str(error)[:2000]
                    try:
                        log_answer(t, i)
                    except Exception:
                        pass
                    t.save()
                    self.cv.notify_all()
                    if not t.keep and t.pending() == 0:
                        t.tab_gone = True  # 페이지가 스스로 탭을 닫는다(window.close)
                    return True, waiting
            return False, False

    def wait(self, sid, id_, timeout, alive=None):
        """Block until the card is answered. `alive` tells whether the CLI is still connected: a CLI that was
        interrupted must not count as a reader, or an answer that arrives later would be marked read and lost."""
        with self.cv:
            t = self.get(sid, create=False)
            end = time.time() + timeout
            key = (t.sid if t else sid, id_)
            self.waiting += 1
            self.waiting_on.setdefault(key, []).append(alive)
            try:
                while True:
                    it = next((i for i in (t.items if t else []) if i["id"] == id_), None)
                    if it is None:
                        return {"status": "unknown"}
                    if alive and not alive():
                        return None
                    if it["answer"] is not None:
                        if not it.get("consumed"):
                            it["consumed"] = True
                            t.save()
                            log_event("read", session=t.sid, id=id_, via="wait")
                        return it["answer"]
                    if time.time() >= end:
                        return None
                    self.cv.wait(min(5.0, max(0.0, end - time.time())))
            finally:
                self.waiting -= 1
                self.waiting_on[key].remove(alive)
                if not self.waiting_on[key]:
                    del self.waiting_on[key]

    def take_unread(self, sid):
        """Hand over answers that arrived while no CLI was waiting (after an ask timed out), once."""
        with self.cv:
            t = self.get(sid, create=False)
            out = []
            for i in (t.unread() if t else []):
                i["consumed"] = True
                a = i["answer"]
                row = {"id": i["id"], "title": i.get("title"), "status": a.get("status"), "answers": a.get("answers"),
                       "asked_at": i.get("ts"), "answered_at": a.get("answered_at"), "log": a.get("log")}
                if a.get("error"):
                    row["error"] = a["error"]
                out.append(row)
                log_event("read", session=t.sid, id=i["id"], via="late")
            if out:
                t.save()
            return out

    def health(self, sid=None):
        with self.cv:
            out = {"ok": True, "pid": os.getpid(), "threads": len(self.threads), "version": VERSION,
                   "pending_total": sum(x.pending() for x in self.threads.values()), "waiting_total": self.waiting}
            if sid:
                t = self.get(sid, create=False)
                out.update(client_fresh=bool(t and t.has_client()), pending=t.pending() if t else 0, items=len(t.items) if t else 0,
                           delivered=t.delivered if t else 0, unread=len(t.unread()) if t else 0,
                           label=t.label if t else None)
            else:
                out["list"] = [{"session": t.sid, "label": t.label, "pending": t.pending(), "items": len(t.items), "client": t.has_client()}
                               for t in self.threads.values()]
            return out


def collect_paths(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("src", "img", "image") and isinstance(v, str) and v.startswith("/") and os.path.isfile(v):
                acc.add(os.path.realpath(v))
            else:
                collect_paths(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            collect_paths(v, acc)
    return acc


MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
        ".svg": "image/svg+xml", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".avif": "image/avif", ".bmp": "image/bmp", ".ico": "image/x-icon", ".apng": "image/apng", ".m4v": "video/mp4"}

INDEX = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="same-origin"><title>ask-ui 세션 목록</title><link rel="icon" href="data:,"><style>%s</style></head><body><main>
<h1 style="font-size:20px">ask-ui 세션</h1><div class="card">%s</div></main></body></html>"""


def run_daemon(port):
    os.makedirs(THREADS_DIR, exist_ok=True)
    # 두 세션이 동시에 데몬을 띄워도 하나만 남게 한다(나머지는 조용히 끝나고 CLI 는 살아남은 쪽에 붙는다)
    try:
        import fcntl
        global _lock
        _lock = open(LOCK_FILE, "w")
        for attempt in range(20):  # 방금 stop 된 데몬이 내려가는 중일 수 있어 2초까지 기다린다
            try:
                fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if attempt == 19:
                    return
                time.sleep(0.1)
    except ImportError:
        pass
    d = Daemon()
    page = PAGE.encode("utf-8")

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

        def peer_alive(self):
            # 기다리던 CLI 가 끊겼는지(사용자가 중단) 본다: 읽을 것이 있는데 0바이트면 상대가 닫은 것
            try:
                if select.select([self.connection], [], [], 0)[0]:
                    return self.connection.recv(1, socket.MSG_PEEK) != b""
            except (OSError, ValueError):
                return False
            return True

        def guard(self):
            # 다른 웹페이지가 이 로컬 서버로 카드를 밀어 넣거나 답을 읽지 못하게 한다.
            # Host 는 DNS rebinding, Origin 은 다른 출처의 fetch/form 을 막는다(CLI 는 Origin 을 보내지 않는다).
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            origin = self.headers.get("Origin")
            ok = host in ("127.0.0.1", "localhost") and (
                not origin or origin in ("http://127.0.0.1:%d" % d.port, "http://localhost:%d" % d.port))
            if not ok:
                self.send(403, {"error": "forbidden"})
            return ok

        def send_file(self, p):
            size = os.path.getsize(p)
            start, end, code = 0, size - 1, 200
            m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
            if m and (m.group(1) or m.group(2)):  # 영상 탐색에 필요
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", MIME[os.path.splitext(p)[1].lower()])
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            if code == 206:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.end_headers()
            with open(p, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def do_GET(self):
            if not self.guard():
                return
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            sid = qs.get("s", [None])[0]
            if u.path.startswith("/t/"):
                return self.send(200, page, "text/html; charset=utf-8")
            if u.path == "/":
                rows = []
                for t in list(d.threads.values()):
                    rows.append('<div style="padding:6px 0"><a href="/t/%s">%s</a> · 카드 %d · 대기 %d</div>'
                                % (urllib.parse.quote(t.sid), html.escape(t.label), len(t.items), t.pending()))
                return self.send(200, (INDEX % (CSS, "".join(rows) or "열린 세션 없음")).encode("utf-8"), "text/html; charset=utf-8")
            if u.path == "/events":
                return self.send(200, d.events(sid, int(qs.get("since", ["0"])[0]), min(float(qs.get("wait", ["25"])[0]), 30)))
            if u.path == "/wait":
                r = d.wait(sid, int(qs["id"][0]), float(qs.get("timeout", ["590"])[0]), self.peer_alive)
                return self.send(200, r or {"status": "timeout"})
            if u.path == "/health":
                return self.send(200, d.health(sid))
            if u.path == "/file":
                p = os.path.realpath(qs.get("p", [""])[0])
                t = d.get(sid, create=False) if sid else None
                allowed = t.files if t else set().union(*[x.files for x in d.threads.values()] or [set()])
                if p not in allowed or os.path.splitext(p)[1].lower() not in MIME:
                    return self.send(403, {"error": "not allowed"})
                if not os.path.isfile(p):
                    return self.send(404, {"error": "file is gone"})
                return self.send_file(p)
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if not self.guard():
                return
            u = urllib.parse.urlparse(self.path)
            if u.path == "/push":
                b = self.body()
                return self.send(200, {"id": d.push(b.get("session"), b.get("spec", {}), b.get("label"), b.get("keep"))})
            if u.path == "/bye":
                d.bye(self.body().get("session"))
                return self.send(200, {"ok": True})
            if u.path == "/answer":
                b = self.body()
                ok, waiting = d.answer(b.get("session"), int(b.get("id", 0)), b.get("status", "submitted"), b.get("answers", {}),
                                       b.get("diag"), b.get("error"))
                return self.send(200, {"ok": ok, "waiting": waiting})
            if u.path == "/unread":
                return self.send(200, {"answers": d.take_unread(self.body().get("session"))})
            if u.path == "/stop":
                self.send(200, {"ok": True})
                threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
                return
            self.send(404, {"error": "not found"})

    # 늘 같은 포트를 먼저 쓴다. 데몬이 바뀌어도 열려 있던 탭이 같은 주소로 다시 붙는다. 0 = 임의 포트
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PREFERRED_PORT if port is None else port), H)
    except OSError:
        if port is not None:
            raise
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    d.port = srv.server_address[1]
    os.makedirs(BASE, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"port": srv.server_address[1], "pid": os.getpid(), "started": time.time()}, f)
    try:  # 측정 자료라 지우지 않고 한 벌만 밀어 둔다. 5MB = 한 줄 약 120바이트 기준 약 4만 건(내가 정한 값)
        if os.path.getsize(EVENTS_FILE) > 5 * 1024 * 1024:
            os.replace(EVENTS_FILE, EVENTS_FILE + ".1")
    except OSError:
        pass
    log_event("daemon", version=VERSION, port=d.port, pid=os.getpid())

    def reaper():
        while True:
            time.sleep(60)
            if time.time() - d.last_activity > IDLE_EXIT_SEC:
                os._exit(0)
    threading.Thread(target=reaper, daemon=True).start()
    srv.serve_forever()


def log_event(kind, **kw):
    """One line per event (push, seen, answer, read, daemon start). No card contents: this is for measuring how the
    tool is used (answers that came late, cards never seen), which the answer history alone cannot show."""
    try:
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict({"t": round(time.time(), 1), "kind": kind}, **kw), ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_answer(t, it):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = os.path.join(HISTORY_DIR, datetime.now().strftime("%Y%m%d-%H%M%S") + "-%s-%d.json" % (t.sid[:8], it["id"]))
    spec = {k: v for k, v in it.items() if k not in ("seq", "done", "answer")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"session": t.sid, "label": t.label, "spec": spec, "result": it["answer"]}, f, ensure_ascii=False, indent=2)
    it["answer"]["log"] = path


# ============================================================ client
def state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def api(port, path, data=None, timeout=10):
    url = "http://127.0.0.1:%d%s" % (port, path)
    req = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def health(sid=None):
    st = state()
    if not st:
        return None, None
    try:
        q = "?s=" + urllib.parse.quote(sid) if sid else ""
        return st["port"], api(st["port"], "/health" + q, timeout=2)
    except Exception:
        return None, None


def ensure_daemon(sid=None):
    port, h = health(sid)
    if h and h.get("version") != VERSION:
        # 스크립트가 갱신됐는데 예전 데몬이 떠 있다. 답을 기다리며 멈춰 있는 CLI 가 없을 때만 바꾼다(이력은 threads/ 에서 복원).
        # 기다리는 CLI 수를 모르는 예전 데몬은 대기 중인 질문 수로 판단한다.
        _, hall = health()
        hall = hall or {}
        busy = hall.get("waiting_total")
        if busy is None:
            busy = sum(x.get("pending", 0) for x in hall.get("list", []))
        if busy:
            print("ask_ui: daemon is an older version; kept because %d ask(s) are waiting on it" % busy, file=sys.stderr)
            return port, h
        try:
            api(port, "/stop", {})
        except Exception:
            pass
        for _ in range(30):
            time.sleep(0.1)
            if not health()[1]:
                break
        h = None
    if h:
        return port, h
    fixed = os.environ.get("ASK_UI_PORT")  # 테스트나 포트 충돌 때만 쓴다
    os.makedirs(BASE, exist_ok=True)
    log = os.path.join(BASE, "daemon.log")  # 데몬 안에서 난 오류를 남긴다(평소엔 비어 있다)
    with open(log, "w" if not os.path.exists(log) or os.path.getsize(log) > 1 << 20 else "a") as errlog:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "serve"] + (["--port", fixed] if fixed else []),
                         stdout=subprocess.DEVNULL, stderr=errlog, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(50):
        time.sleep(0.1)
        port, h = health(sid)
        if h:
            return port, h
    sys.exit("ask_ui: daemon failed to start")


def notify(title, text):
    if sys.platform != "darwin":
        return
    try:
        # 글자를 스크립트에 끼워 넣지 않고 인자로 넘긴다(따옴표, 역슬래시, 줄바꿈이 있어도 안전)
        subprocess.run(["osascript", "-e", "on run a", "-e", "display notification (item 2 of a) with title (item 1 of a)",
                        "-e", "end run", title, text[:120]], timeout=3, capture_output=True)
    except Exception:
        pass


def load_spec(p):
    """스펙을 읽고 점검한다. 깨진 카드가 탭에 뜨는 대신 여기서 이유를 알려 준다."""
    try:
        spec = json.load(sys.stdin if p == "-" else open(p, encoding="utf-8"))
    except (OSError, ValueError) as e:
        spec, problems = None, ["cannot read spec: %s" % e]
    else:
        problems, missing, warnings = prepare_spec(spec, os.getcwd() if p == "-" else os.path.dirname(os.path.abspath(p)))
        MISSING[:] = missing
        WARNINGS[:] = warnings
        for m in missing:
            print("ask_ui: warning: %s (the card will show an empty box)" % m, file=sys.stderr)
        for m in warnings:
            print("ask_ui: warning: " + m, file=sys.stderr)
    if problems:
        for m in problems:
            print("ask_ui: " + m, file=sys.stderr)
        print(json.dumps({"status": "error", "error": "invalid spec", "problems": problems}, ensure_ascii=False))
        sys.exit(1)
    return spec


MISSING = []  # 스펙에 적혔지만 쓸 수 없는 로컬 파일. 결과 JSON 의 "missing" 으로 돌려준다
WARNINGS = []  # 페이지가 쓰지 않는 키(오타, 없는 기능). 결과 JSON 의 "warnings" 로 돌려준다
KNOWN = {
    "card": {"title", "why", "intro", "auto_submit", "submit_label", "content", "questions", "note"},
    "content block": {"type", "text", "lang", "caption", "src", "loop", "height", "items"},
    "compare item": {"label", "image", "html", "code", "text", "height"},
    "question": {"id", "type", "label", "desc", "required", "other", "other_placeholder", "options", "min", "max",
                 "min_label", "max_label", "default", "step", "placeholder", "rows", "show_if", "aspect", "mode", "labels"},
    "option": {"value", "label", "desc", "recommended", "img", "html", "url"},
}
Q_TYPES = ("single", "multi", "scale", "text", "rank", "image", "rate")
Q_NEED_OPTIONS = ("single", "multi", "rank", "image", "rate")
BLOCK_NEEDS = {"markdown": "text", "code": "text", "diff": "text", "html": "text", "mermaid": "text", "image": "src", "video": "src"}


def prepare_spec(spec, base):
    """Fix what can be fixed in place (missing question ids, ~ and relative file paths).
    Returns (problems, missing, warnings): problems would leave the user looking at a broken card and stop the push;
    missing lists local files that cannot be shown and warnings lists keys the page ignores (the card still goes
    up in both cases, as it did before)."""
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"], [], []
    bad, missing, unknown = [], [], {}

    def known(kind, obj):
        for k in obj:
            if k not in KNOWN[kind]:
                unknown.setdefault((kind, k), 0)
                unknown[(kind, k)] += 1
    for key in ("content", "questions"):
        v = spec.get(key)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, dict) for x in v)):
            bad.append("%s must be a list of objects" % key)
    if bad:
        return bad, missing, []
    known("card", spec)
    for n, b in enumerate(spec.get("content") or [], 1):
        known("content block", b)
        for it in b["items"] if b.get("type") == "compare" and isinstance(b.get("items"), list) else []:
            if isinstance(it, dict):
                known("compare item", it)
        need = BLOCK_NEEDS.get(b.get("type"))
        if need and not isinstance(b.get(need), str):
            bad.append("content[%d] (%s) needs a string '%s'" % (n, b.get("type"), need))
        if b.get("type") == "compare" and not isinstance(b.get("items"), list):
            bad.append("content[%d] (compare) needs 'items'" % n)
    seen = set()
    qs = spec.get("questions") or []
    for n, q in enumerate(qs, 1):
        known("question", q)
        for o in q.get("options") or [] if isinstance(q.get("options"), list) else []:
            if isinstance(o, dict):
                known("option", o)
        if q.get("id") in (None, ""):
            q["id"] = "q%d" % n
        q["id"] = str(q["id"])
        if q["id"] in seen:
            bad.append("question id '%s' is used twice" % q["id"])
        seen.add(q["id"])
        if q.get("type") not in Q_TYPES:
            bad.append("question '%s': unknown type %r (use %s)" % (q["id"], q.get("type"), "/".join(Q_TYPES)))
        elif q["type"] in Q_NEED_OPTIONS and not (isinstance(q.get("options"), list) and q["options"]) \
                and not (q.get("other") and q.get("options") in (None, [])):  # 선택지 없이 '기타' 입력만 있는 질문은 쓸 수 있다
            bad.append("question '%s' (%s) needs non-empty 'options'" % (q["id"], q["type"]))
    for q in qs:
        c = q.get("show_if")
        if isinstance(c, dict) and str(c.get("q")) not in seen:
            bad.append("question '%s': show_if points at unknown question %r" % (q["id"], c.get("q")))

    def paths(o):
        if isinstance(o, list):
            for x in o:
                paths(x)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ("src", "img", "image") and isinstance(v, str) and v and not re.match(r"(https?:|data:|blob:|//)", v):
                    p = os.path.expanduser(v)
                    p = p if os.path.isabs(p) else os.path.join(base, p)
                    if not os.path.isfile(p):
                        missing.append("file not found: %s" % v)
                    elif os.path.splitext(p)[1].lower() not in MIME:
                        missing.append("unsupported file type: %s (use %s)" % (v, " ".join(sorted(MIME))))
                    else:
                        o[k] = os.path.abspath(p)
                else:
                    paths(v)
    paths(spec)
    warnings = ["unknown %s key '%s' is ignored%s" % (kind, k, " (%d times)" % c if c > 1 else "")
                for (kind, k), c in sorted(unknown.items())]
    return bad, missing, warnings


def session_id(explicit=None):
    return safe_sid(explicit or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default")


def session_label(sid):
    return "%s · %s" % (os.path.basename(os.getcwd()) or "/", sid[:6])


def thread_url(port, sid):
    return "http://127.0.0.1:%d/t/%s" % (port, urllib.parse.quote(sid))


def finish(out, port, sid):
    """Attach what Claude must not miss to the one JSON line every command prints."""
    if MISSING:
        out["missing"] = list(MISSING)
    if WARNINGS:
        out["warnings"] = list(WARNINGS)
    try:  # 타임아웃 뒤에 온 답. 한 번만 전달된다
        late = api(port, "/unread", {"session": sid}, timeout=5).get("answers")
        if late:
            out["late_answers"] = late
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False))


def cmd_push(spec, open_browser, quiet, wait, timeout, sid):
    port, h = ensure_daemon(sid)
    id_ = api(port, "/push", {"session": sid, "label": session_label(sid), "spec": spec, "keep": KEEP_OPEN})["id"]
    url = thread_url(port, sid)
    if open_browser and not h.get("client_fresh"):
        webbrowser.open(url)
        print("ask_ui: opened browser", file=sys.stderr)
    elif not quiet and spec.get("questions"):
        notify("Claude 질문 · " + session_label(sid), spec.get("title") or (spec["questions"][0].get("label", "")))
    print("ask_ui: item %d at %s" % (id_, url), file=sys.stderr)
    if not wait:
        finish({"status": "shown", "id": id_, "url": url, "session": sid}, port, sid)
        return 0
    if open_browser and h.get("client_fresh"):
        # 탭이 있다고 봤지만 실제로는 죽었을 수 있다(브라우저 종료, 탭 절전). 3초 안에 카드를 받아 가지 않으면 새 탭을 연다
        for _ in range(15):
            time.sleep(0.2)
            try:
                if api(port, "/health?s=" + urllib.parse.quote(sid), timeout=2).get("delivered", id_) >= id_:
                    break
            except Exception:
                break
        else:
            webbrowser.open(url)
            print("ask_ui: tab did not pick up the card; opened browser", file=sys.stderr)
    return cmd_wait(id_, timeout, sid, port)


def cmd_wait(id_, timeout, sid, port=None):
    if port is None:  # ask 는 카드를 올린 바로 그 데몬에서 기다린다
        port, h = health(sid)
        if not h:
            print(json.dumps({"status": "error", "error": "daemon not running"}))
            return 1
    t0 = time.time()
    try:
        r = api(port, "/wait?s=%s&id=%d&timeout=%d" % (urllib.parse.quote(sid), id_, int(timeout)), timeout=timeout + 15)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        return 1
    r["id"] = id_
    r["session"] = sid
    r["elapsed_sec"] = round(time.time() - t0, 1)
    finish(r, port, sid)
    return {"submitted": 0, "timeout": 2, "cancelled": 3}.get(r.get("status"), 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["ask", "show", "wait", "cancel", "status", "list", "stop", "open", "serve"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--timeout", type=float, default=590)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="no macOS notification")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--session", help="thread id (default: $CLAUDE_CODE_SESSION_ID)")
    a = ap.parse_args()
    sid = session_id(a.session)
    if a.cmd == "serve":
        return run_daemon(a.port)
    if a.cmd == "ask":
        if not a.arg:
            ap.error("spec required")
        spec = load_spec(a.arg)
        # 질문이 없는 카드는 답할 것이 없다. 타임아웃까지 멈추지 않고 show 처럼 바로 돌아온다
        return sys.exit(cmd_push(spec, not a.no_open, a.quiet, bool(spec.get("questions")), a.timeout, sid))
    if a.cmd == "show":
        if not a.arg:
            ap.error("spec required")
        spec = load_spec(a.arg)
        spec.pop("questions", None)
        return sys.exit(cmd_push(spec, not a.no_open, True, False, 0, sid))
    if a.cmd == "wait":
        if not (a.arg or "").isdigit():
            ap.error("wait needs the card id printed by ask")
        return sys.exit(cmd_wait(int(a.arg), a.timeout, sid))
    if a.cmd == "cancel":
        if not (a.arg or "").isdigit():
            ap.error("cancel needs the card id printed by ask")
        port, h = health(sid)
        ok = bool(h) and api(port, "/answer", {"session": sid, "id": int(a.arg), "status": "cancelled", "answers": {},
                                               "diag": {"by": "caller"}})["ok"]
        finish({"status": "withdrawn" if ok else "error", "id": int(a.arg), "session": sid,
                **({} if ok else {"error": "no pending card with that id"})}, port, sid)
        return sys.exit(0 if ok else 1)
    if a.cmd == "status":
        port, h = health(sid)
        print(json.dumps({"running": bool(h), "port": port, "session": sid, **(h or {})}, ensure_ascii=False))
        return
    if a.cmd == "list":
        port, h = health()
        print(json.dumps({"running": bool(h), "port": port, "threads": (h or {}).get("list", [])}, ensure_ascii=False, indent=1))
        return
    if a.cmd == "stop":
        port, h = health()
        if h:
            try:
                api(port, "/stop", {})
            except Exception:
                pass
        for f_ in (STATE_FILE,):
            try:
                os.remove(f_)
            except OSError:
                pass
        for fn in os.listdir(THREADS_DIR) if os.path.isdir(THREADS_DIR) else []:
            try:  # 아직 Claude 가 못 읽은 답은 지우기 전에 내놓는다
                with open(os.path.join(THREADS_DIR, fn), encoding="utf-8") as f:
                    late = [{"id": i["id"], "title": i.get("title"), "status": i["answer"].get("status"), "answers": i["answer"].get("answers")}
                            for i in json.load(f).get("items", []) if i.get("answer") and not i.get("consumed", True)]
                if late:
                    print(json.dumps({"session": fn[:-5], "late_answers": late}, ensure_ascii=False))
            except (OSError, ValueError, KeyError, AttributeError):
                pass
            try:
                os.remove(os.path.join(THREADS_DIR, fn))
            except OSError:
                pass
        print("stopped")
        return
    if a.cmd == "open":
        port, h = ensure_daemon(sid)
        webbrowser.open(thread_url(port, sid))


if __name__ == "__main__":
    main()
