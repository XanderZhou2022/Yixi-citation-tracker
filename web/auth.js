const $ = id => document.getElementById(id);
let envelope, rawKey, onUnlock;
const basePath = new URL('.', location.href).pathname;
const b64 = bytes => btoa(String.fromCharCode(...bytes));
const unb64 = value => Uint8Array.from(atob(value), c => c.charCodeAt(0));
const cookieName = () => 'citation_key_' + envelope.salt.replace(/[^a-zA-Z0-9]/g, '').slice(0,12);
const secureFlag = () => location.protocol === 'https:' ? '; Secure' : '';
function clearCookie() {
  document.cookie = `${cookieName()}=; Max-Age=0; Path=${basePath}; SameSite=Strict${secureFlag()}`;
}
function rememberKey(bytes) {
  // Browsers cap persistent cookies, typically at 400 days. Never store the password.
  document.cookie = `${cookieName()}=${encodeURIComponent(b64(bytes))}; Max-Age=34560000; Path=${basePath}; SameSite=Strict${secureFlag()}`;
}
function rememberedKey() {
  const pair=document.cookie.split('; ').find(row=>row.startsWith(cookieName()+'='));
  return pair ? unb64(decodeURIComponent(pair.slice(pair.indexOf('=')+1))) : null;
}
async function fetchEnvelope() {
  const response=await fetch('data.enc.json',{cache:'no-store'});
  if(!response.ok) throw new Error('数据暂不可用，请稍后重试。');
  const value=await response.json();
  if(value.format!=='citation-aesgcm-v1'||value.iterations!==600000) throw new Error('数据格式不支持。');
  return value;
}
async function decrypt(value, bytes) {
  const key=await crypto.subtle.importKey('raw',bytes,{name:'AES-GCM'},false,['decrypt']);
  const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:unb64(value.nonce),additionalData:new TextEncoder().encode('citation-v1'),tagLength:128},key,unb64(value.ciphertext));
  return JSON.parse(new TextDecoder().decode(plain));
}
async function unlock(bytes) {
  const payload=await decrypt(envelope,bytes);
  await onUnlock(payload);
  rawKey=bytes;
  rememberKey(bytes);
  $('password').value='';
  $('login').hidden=true;
  $('dashboard').hidden=false;
}
export async function loadSnapshot() {
  if(!rawKey) throw new Error('请先登录。');
  const fresh=await fetchEnvelope();
  return decrypt(fresh,rawKey);
}
export function logout() {
  if(envelope) clearCookie();
  rawKey=null;
  location.reload();
}
export async function initializeAuth(callback) {
  onUnlock=callback;
  $('login-button').disabled=true;
  try {
    if(!crypto.subtle) throw new Error('请通过 HTTPS 打开页面。');
    envelope=await fetchEnvelope();
    try { const saved=rememberedKey();if(saved) await unlock(saved); }
    catch { clearCookie(); }
  } catch(error) { $('login-error').textContent=error.message;return; }
  finally { $('login-button').disabled=false; }
  $('login-form').addEventListener('submit',async event=>{
    event.preventDefault();$('login-button').disabled=true;$('login-error').textContent='';
    const password=$('password').value;$('password').value='';
    try {
      const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveBits']);
      const bits=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:unb64(envelope.salt),iterations:envelope.iterations},material,256);
      await unlock(new Uint8Array(bits));
    } catch { $('login-error').textContent='密码不正确，请重试。'; }
    finally { $('login-button').disabled=false; }
  });
}
