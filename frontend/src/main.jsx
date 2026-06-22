import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Send, ShoppingCart, Settings, Save, Trash2, Pencil, Plus, TestTube, RefreshCw, Download, Lock, LogOut, KeyRound, UserPlus, UserRound } from 'lucide-react';
import { getProducts, getServices, getChatSettings, sendChat, adminList, adminCreate, adminUpdate, adminDelete, testHuggingFace, syncDriveWidget, exportLeadsCsv, loginAdmin, adminMe, changeAdminPassword, logoutAdmin, setAdminToken, registerClient, loginClient, clientMe, logoutClient, setClientToken } from './lib/api';
import './styles.css';

function useVisitorId() {
  return useMemo(() => {
    let id = localStorage.getItem('visitor_id');
    if (!id) { id = crypto.randomUUID(); localStorage.setItem('visitor_id', id); }
    return id;
  }, []);
}

function Money({ value, currency='BHD' }) {
  if (value === null || value === undefined || value === '') return <span>Available</span>;
  return <span>{Number(value).toLocaleString('en-BH', { minimumFractionDigits: 3, maximumFractionDigits: 3 })} {currency}</span>;
}

function Sidebar({ products, services, settings, onPick, onNewChat }) {
  return <aside className="sidebar">
    <div className="sideBrand">
      <div className="brandMark">AI</div>
      <div>
        <strong>{settings.brand_title || 'MaRiffaie AI Assistant'}</strong>
        <small>{settings.brand_subtitle || 'Support Agent'}</small>
      </div>
    </div>
    <button className="newChatBtn" onClick={onNewChat}>New chat</button>
    {(settings.show_services_sidebar ?? true) && <>
      <h3>Services</h3>
      {services.map(s => <button key={s.id} className="sideItem" onClick={() => onPick(`I need help with ${s.name}`)}><span>{s.name}</span><small><Money value={s.price} currency={s.currency} /></small></button>)}
    </>}
    {(settings.show_products_sidebar ?? true) && <>
      <h3>Products</h3>
      {products.map(p => <button key={p.id} className="sideItem" onClick={() => onPick(`Tell me more about ${p.name}`)}><span>{p.name}</span><small><Money value={p.price} currency={p.currency} /></small></button>)}
    </>}
  </aside>;
}

function ProductCard({ product }) {
  return <div className="productCard">
    {product.image_url && <img src={product.image_url} alt="" />}
    <b>{product.name}</b>
    <p>{product.description || 'Professional product/service package.'}</p>
    <div className="row"><span><Money value={product.price} currency={product.currency}/></span><button><ShoppingCart size={16}/> Buy Now</button></div>
  </div>;
}

function ChatPage() {
  const visitorId = useVisitorId();
  const [products, setProducts] = useState([]); const [services, setServices] = useState([]); const [settings, setSettings] = useState({});
  const [messages, setMessages] = useState([]); const [input, setInput] = useState(''); const [loading, setLoading] = useState(false);
  useEffect(() => { getProducts().then(setProducts); getServices().then(setServices); getChatSettings().then(setSettings).catch(()=>{}); }, []);
  function pick(text) { setInput(text); setTimeout(()=>document.querySelector('#chatInput')?.focus(), 10); }
  function newChat() { setMessages([]); setInput(''); setTimeout(()=>document.querySelector('#chatInput')?.focus(), 10); }
  async function submit(e) {
    e.preventDefault(); const text = input.trim(); if (!text || loading) return;
    setInput(''); setMessages(m => [...m, { role:'user', text }]); setLoading(true);
    try { const res = await sendChat({ message: text, visitor_id: visitorId, lang: navigator.language || 'en' }); setMessages(m => [...m, { role:'assistant', text: res.answer, products: res.products || [], sources: res.sources || [] }]); }
    catch { setMessages(m => [...m, { role:'assistant', text:'Sorry, the chat service is unavailable. Please contact info6@malriffaie.com.' }]); }
    finally { setLoading(false); }
  }
  return <div className="appShell chatEnabledHome">
    {(settings.show_sidebar ?? true) && <Sidebar products={products} services={services} settings={settings} onPick={pick} onNewChat={newChat}/>}<main className="chatMain">
      <header className="hero compactHero"><div><h1>{settings.hero_title || 'How can we help you today?'}</h1>{(settings.show_tagline ?? true) && <p>Ask about products, services, pricing, FAQs, or booking.</p>}</div><div className="homeHeaderActions"><a className="adminLink" href="/client-register"><UserPlus size={16}/> Client Registration</a><a className="adminLink" href="/client-login"><UserRound size={16}/> Client Login</a><a className="adminLink" href="/admin"><Settings size={16}/> Admin</a></div></header>
      <section className="messages">
        {!messages.length && <div className="empty"><h3>{settings.empty_state_title || 'Start a conversation'}</h3><p>{settings.empty_state_message || 'I can recommend products, explain services, answer FAQs, and help with bookings.'}</p>{(settings.show_chips ?? true) && <div className="chips"><button onClick={()=>pick('Which product is right for a new business?')}>Recommend a product</button><button onClick={()=>pick('I want to book an online consultation')}>Book consultation</button><button onClick={()=>pick('Tell me about partnership agreements')}>Partnership agreement</button></div>}</div>}
        {messages.map((m,i)=><div key={i} className={`msg ${m.role}`}><p>{m.text}</p>{m.products?.length>0 && <div className="cards">{m.products.map(p=><ProductCard key={p.id} product={p}/>)}</div>}{settings.show_sources && m.sources?.length>0 && <details><summary>Sources</summary><pre>{JSON.stringify(m.sources, null, 2)}</pre></details>}</div>)}
        {loading && <div className="msg assistant"><p>Thinking...</p></div>}
      </section>
      <form className="composer" onSubmit={submit}><input id="chatInput" autoFocus={settings.auto_focus ?? true} value={input} onChange={e=>setInput(e.target.value)} placeholder={settings.input_placeholder || 'Describe what you need...'}/><button><Send size={18}/></button></form>
      <footer>{settings.footer_disclaimer || 'AI responses may need human confirmation for complex cases.'}</footer>
    </main></div>;
}

const tabs = [
  ['ai_settings','AI Concierge Settings'], ['chat_settings','Chat Page Settings'], ['services','Services'], ['products','E-commerce Products'],
  ['knowledge_base','Knowledge Base'], ['google_drive_widgets','Google Drive Widgets'], ['booking_settings','Booking'], ['bookings','Bookings'],
  ['payment_settings','Payment Gateway'], ['payments','Payments'], ['email_settings','Email'], ['leads','Leads'], ['chat_messages','Chat History']
];

const defaults = {
  ai_settings: { replace_homepage_with_chat: true, chat_greeting: 'Hi, I am your support concierge. I can help with our products, services, FAQs, documents, and bookings. What would you like to know?', hugging_face_token: '', model_name: 'Qwen/Qwen3-8B', custom_model_name: '', custom_endpoint_url: '', embedding_model: 'BAAI/bge-m3', custom_embedding_model_name: '', embedding_endpoint_url: '', system_prompt: 'Act as a customer support representative. Answer from Malriffaie knowledge base, products, and services. If not found, say clearly and ask the user to book a consultation.', temperature: 0.3, top_p: 0.9, max_tokens: 512, timeout: 30, retry_count: 2, rate_limit: 10, fallback_message: 'I do not have that information yet. I can arrange a human handoff for you.', use_cases: ['Customer support automation','Website FAQs and knowledge base','E-commerce product assistance','Documentation search','Internal company wikis'], optional_rule: '' },
  chat_settings: { brand_title:'Malriffaie', brand_subtitle:'AI Concierge', hero_title:'How can we help you today?', show_tagline:true, input_placeholder:'Describe what you need...', empty_state_title:'Ask about products, services, or bookings', empty_state_message:'I can recommend the right product or help you book a consultation.', show_chips:true, show_sources:false, sticky_input:true, auto_focus:true, show_sidebar:true, show_services_sidebar:true, show_products_sidebar:true, footer_disclaimer:'AI responses may need human confirmation for complex cases.' },
  products: { name:'', description:'', price:'', currency:'BHD', image_url:'', available:true },
  services: { name:'', description:'', price:'', currency:'BHD', available:true },
  knowledge_base: { source_type:'manual', source_id:'', content:'', metadata:{} },
  google_drive_widgets: { api_key:'', folder_id:'', folder_url:'', enabled:false, sync_interval_minutes:1440 },
  booking_settings: { enabled:true, manual_fallback_enabled:true, google_calendar_enabled:false, api_key:'', calendar_id:'', timezone:'Asia/Bahrain', default_duration:60, buffer_minutes:15, work_start:'09:00', work_end:'17:00', working_days:['sun','mon','tue','wed','thu'], service_product_map:{} },
  bookings: { user_id:null, service_id:null, product_id:null, datetime:'', status:'pending', google_calendar_id:'' },
  payment_settings: { mode:'manual', tap_enabled:false, manual_transfer_enabled:true, pending_message:'Your order is pending review. Please complete Benefit transfer and we will confirm shortly.' },
  payments: { booking_id:null, amount:'', currency:'BHD', method:'manual', status:'pending', transaction_id:'' },
  email_settings: { admin_email:'info6@malriffaie.com', confirmation_subject:'Booking confirmation', confirmation_body:'Thank you. Your booking has been received.', reminder_body:'Reminder: your booking is coming up soon.' },
  leads: { user_id:null, name:'', email:'', product_id:null, status:'new', paid:false },
};

const useCaseOptions = ['Customer support automation','Website FAQs and knowledge base','E-commerce product assistance','Educational content interaction','Documentation search','Internal company wikis','Services'];
const modelOptions = ['Qwen/Qwen3-8B','meta-llama/Llama-3.1-8B-Instruct','mistralai/Mistral-7B-Instruct-v0.3','google/gemma-2-2b-it','HuggingFaceH4/zephyr-7b-beta','custom'];
const embeddingOptions = ['BAAI/bge-m3','sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2','sentence-transformers/paraphrase-multilingual-mpnet-base-v2','custom'];

function cleanPayload(table, form) {
  const payload = { ...form };
  delete payload.id; delete payload.created_at; delete payload.updated_at; delete payload.synced_at;
  if ('price' in payload) payload.price = payload.price === '' ? null : Number(payload.price);
  if ('amount' in payload) payload.amount = payload.amount === '' ? null : Number(payload.amount);
  if (payload.user_id === '') payload.user_id = null;
  if (payload.service_id === '') payload.service_id = null;
  if (payload.product_id === '') payload.product_id = null;
  if (payload.booking_id === '') payload.booking_id = null;
  if (table === 'ai_settings') {
    if (payload.model_name === 'custom') payload.model_name = payload.custom_model_name;
    if (payload.embedding_model === 'custom') payload.embedding_model = payload.custom_embedding_model_name;
    delete payload.custom_model_name;
    delete payload.custom_embedding_model_name;
  }
  return payload;
}

function Field({ label, help, children }) { return <label className="formRow"><span>{label}</span><div>{children}{help && <small>{help}</small>}</div></label>; }
function Text({ value='', onChange, type='text', placeholder='' }) { return <input type={type} value={value ?? ''} placeholder={placeholder} onChange={e=>onChange(e.target.value)} />; }
function Textarea({ value='', onChange, rows=4 }) { return <textarea value={value ?? ''} rows={rows} onChange={e=>onChange(e.target.value)} />; }
function Check({ checked=false, onChange, label='Enabled' }) { return <label className="check"><input type="checkbox" checked={!!checked} onChange={e=>onChange(e.target.checked)} /> {label}</label>; }
function Select({ value='', onChange, children }) { return <select value={value ?? ''} onChange={e=>onChange(e.target.value)}>{children}</select>; }

function AiSettingsForm({ form, setForm }) {
  const set = (k,v) => setForm(f=>({ ...f, [k]:v }));
  const useCases = form.use_cases || [];
  const toggleUseCase = (name, checked) => set('use_cases', checked ? [...new Set([...useCases, name])] : useCases.filter(x=>x!==name));
  return <div className="settingsForm">
    <Field label="Replace homepage with chat"><Check checked={form.replace_homepage_with_chat ?? true} onChange={v=>set('replace_homepage_with_chat', v)} /></Field>
    <Field label="Chat greeting"><Textarea rows={5} value={form.chat_greeting} onChange={v=>set('chat_greeting', v)} /></Field>
    <Field label="Perfect For" help="Select the use cases this assistant should be optimized for. These options are added to the prompt context."><div className="checkStack">{useCaseOptions.map(opt=><Check key={opt} label={opt} checked={useCases.includes(opt)} onChange={v=>toggleUseCase(opt, v)} />)}</div></Field>
    <Field label="Hugging Face access token" help="Stored in backend/Supabase settings and never exposed to frontend JS."><Text type="password" value={form.hugging_face_token} onChange={v=>set('hugging_face_token', v)} /></Field>
    <Field label="Model" help="Recommended chat model: Qwen/Qwen3-8B. Other Hugging Face instruct models are still available."><Select value={form.model_name} onChange={v=>set('model_name', v)}>{modelOptions.map(m=><option key={m} value={m}>{m === 'custom' ? 'Custom model name' : m}</option>)}</Select></Field>
    <Field label="Custom model name"><Text value={form.custom_model_name || ''} onChange={v=>set('custom_model_name', v)} /></Field>
    <Field label="Custom Hugging Face-compatible endpoint URL"><Text value={form.custom_endpoint_url} onChange={v=>set('custom_endpoint_url', v)} /></Field>
    <Field label="Embedding model" help="Recommended: BAAI/bge-m3 for multilingual semantic retrieval from Malriffaie PDFs."><Select value={form.embedding_model} onChange={v=>set('embedding_model', v)}>{embeddingOptions.map(m=><option key={m} value={m}>{m === 'custom' ? 'Custom embedding model name' : m}</option>)}</Select></Field>
    <Field label="Custom embedding model name"><Text value={form.custom_embedding_model_name || ''} onChange={v=>set('custom_embedding_model_name', v)} /></Field>
    <Field label="Embedding endpoint URL"><Text value={form.embedding_endpoint_url} onChange={v=>set('embedding_endpoint_url', v)} /></Field>
    <Field label="System prompt"><Textarea rows={6} value={form.system_prompt} onChange={v=>set('system_prompt', v)} /></Field>
    <Field label="Optional extra rule"><Textarea rows={3} value={form.optional_rule} onChange={v=>set('optional_rule', v)} /></Field>
    <div className="grid2"><Field label="Temperature"><Text type="number" value={form.temperature} onChange={v=>set('temperature', Number(v))} /></Field><Field label="Top P"><Text type="number" value={form.top_p} onChange={v=>set('top_p', Number(v))} /></Field><Field label="Max tokens"><Text type="number" value={form.max_tokens} onChange={v=>set('max_tokens', Number(v))} /></Field><Field label="Timeout seconds"><Text type="number" value={form.timeout} onChange={v=>set('timeout', Number(v))} /></Field><Field label="Retry count"><Text type="number" value={form.retry_count} onChange={v=>set('retry_count', Number(v))} /></Field><Field label="Requests/IP/min"><Text type="number" value={form.rate_limit} onChange={v=>set('rate_limit', Number(v))} /></Field></div>
    <Field label="Fallback message"><Textarea rows={3} value={form.fallback_message} onChange={v=>set('fallback_message', v)} /></Field>
  </div>;
}

function ChatSettingsForm({ form, setForm }) {
  const set=(k,v)=>setForm(f=>({ ...f, [k]:v }));
  return <div className="settingsForm">
    <Field label="Brand title"><Text value={form.brand_title} onChange={v=>set('brand_title', v)} /></Field>
    <Field label="Brand subtitle"><Text value={form.brand_subtitle} onChange={v=>set('brand_subtitle', v)} /></Field>
    <Field label="Hero title"><Text value={form.hero_title} onChange={v=>set('hero_title', v)} /></Field>
    <Field label="Site tagline"><Check checked={form.show_tagline} onChange={v=>set('show_tagline', v)} /></Field>
    <Field label="Input placeholder"><Text value={form.input_placeholder} onChange={v=>set('input_placeholder', v)} /></Field>
    <Field label="Empty state title"><Text value={form.empty_state_title} onChange={v=>set('empty_state_title', v)} /></Field>
    <Field label="Empty state message"><Textarea rows={3} value={form.empty_state_message} onChange={v=>set('empty_state_message', v)} /></Field>
    <Field label="Display options"><div className="checkStack"><Check label="Show suggestion chips" checked={form.show_chips} onChange={v=>set('show_chips', v)} /><Check label="Display sources" checked={form.show_sources} onChange={v=>set('show_sources', v)} /><Check label="Sticky input bar" checked={form.sticky_input} onChange={v=>set('sticky_input', v)} /><Check label="Auto-focus input" checked={form.auto_focus} onChange={v=>set('auto_focus', v)} /><Check label="Show sidebar" checked={form.show_sidebar} onChange={v=>set('show_sidebar', v)} /><Check label="Show services in sidebar" checked={form.show_services_sidebar} onChange={v=>set('show_services_sidebar', v)} /><Check label="Show products in sidebar" checked={form.show_products_sidebar} onChange={v=>set('show_products_sidebar', v)} /></div></Field>
    <Field label="Footer disclaimer"><Textarea rows={3} value={form.footer_disclaimer} onChange={v=>set('footer_disclaimer', v)} /></Field>
  </div>;
}

function ProductServiceForm({ table, form, setForm }) {
  const set=(k,v)=>setForm(f=>({ ...f, [k]:v }));
  return <div className="settingsForm">
    <Field label="Name"><Text value={form.name} onChange={v=>set('name', v)} /></Field>
    <Field label="Description"><Textarea rows={4} value={form.description} onChange={v=>set('description', v)} /></Field>
    <div className="grid2"><Field label="Price"><Text type="number" value={form.price ?? ''} onChange={v=>set('price', v)} /></Field><Field label="Currency"><Text value={form.currency || 'BHD'} onChange={v=>set('currency', v)} /></Field></div>
    {table === 'products' && <Field label="Image URL"><Text value={form.image_url || ''} onChange={v=>set('image_url', v)} /></Field>}
    <Field label="Available"><Check checked={form.available} onChange={v=>set('available', v)} /></Field>
  </div>;
}

function BookingForm({ form, setForm }) { const set=(k,v)=>setForm(f=>({ ...f, [k]:v })); return <div className="settingsForm"><Field label="Date/time"><Text type="datetime-local" value={form.datetime || ''} onChange={v=>set('datetime', v)} /></Field><Field label="Status"><Select value={form.status} onChange={v=>set('status', v)}><option>pending</option><option>confirmed</option><option>cancelled</option><option>completed</option></Select></Field><Field label="Service ID"><Text value={form.service_id || ''} onChange={v=>set('service_id', v)} /></Field><Field label="Product ID"><Text value={form.product_id || ''} onChange={v=>set('product_id', v)} /></Field><Field label="Google Calendar ID"><Text value={form.google_calendar_id || ''} onChange={v=>set('google_calendar_id', v)} /></Field></div>; }
function BookingSettingsForm({ form, setForm }) { const set=(k,v)=>setForm(f=>({ ...f, [k]:v })); const days=form.working_days||[]; const t=(d,v)=>set('working_days', v?[...new Set([...days,d])]:days.filter(x=>x!==d)); return <div className="settingsForm"><Field label="Booking flow"><Check checked={form.enabled} onChange={v=>set('enabled', v)} /></Field><Field label="Manual booking fallback"><Check checked={form.manual_fallback_enabled} onChange={v=>set('manual_fallback_enabled', v)} /></Field><Field label="Google Calendar sync"><Check checked={form.google_calendar_enabled} onChange={v=>set('google_calendar_enabled', v)} /></Field><Field label="Google Calendar API key"><Text type="password" value={form.api_key || ''} onChange={v=>set('api_key', v)} /></Field><Field label="Calendar ID"><Text value={form.calendar_id || ''} onChange={v=>set('calendar_id', v)} /></Field><Field label="Timezone"><Text value={form.timezone || 'Asia/Bahrain'} onChange={v=>set('timezone', v)} /></Field><div className="grid2"><Field label="Default duration"><Text type="number" value={form.default_duration} onChange={v=>set('default_duration', Number(v))} /></Field><Field label="Buffer minutes"><Text type="number" value={form.buffer_minutes} onChange={v=>set('buffer_minutes', Number(v))} /></Field><Field label="Work start"><Text type="time" value={form.work_start} onChange={v=>set('work_start', v)} /></Field><Field label="Work end"><Text type="time" value={form.work_end} onChange={v=>set('work_end', v)} /></Field></div><Field label="Working days"><div className="checkStack inline">{['sun','mon','tue','wed','thu','fri','sat'].map(d=><Check key={d} label={d} checked={days.includes(d)} onChange={v=>t(d,v)} />)}</div></Field></div>; }
function DriveForm({ form, setForm }) { const set=(k,v)=>setForm(f=>({ ...f, [k]:v })); return <div className="settingsForm"><Field label="Enabled"><Check checked={form.enabled} onChange={v=>set('enabled', v)} /></Field><Field label="Google Drive API key"><Text type="password" value={form.api_key || ''} onChange={v=>set('api_key', v)} /></Field><Field label="Folder ID"><Text value={form.folder_id || ''} onChange={v=>set('folder_id', v)} /></Field><Field label="Folder URL"><Text value={form.folder_url || ''} onChange={v=>set('folder_url', v)} /></Field><Field label="Sync interval minutes"><Text type="number" value={form.sync_interval_minutes} onChange={v=>set('sync_interval_minutes', Number(v))} /></Field></div>; }
function PaymentSettingsForm({ form, setForm }) { const set=(k,v)=>setForm(f=>({ ...f, [k]:v })); return <div className="settingsForm"><Field label="Payment mode"><Select value={form.mode} onChange={v=>set('mode', v)}><option>manual</option><option>tap</option><option>both</option></Select></Field><Field label="Tap payment"><Check checked={form.tap_enabled} onChange={v=>set('tap_enabled', v)} /></Field><Field label="Manual Benefit Transfer"><Check checked={form.manual_transfer_enabled} onChange={v=>set('manual_transfer_enabled', v)} /></Field><Field label="Pending review message"><Textarea rows={4} value={form.pending_message} onChange={v=>set('pending_message', v)} /></Field></div>; }
function EmailSettingsForm({ form, setForm }) { const set=(k,v)=>setForm(f=>({ ...f, [k]:v })); return <div className="settingsForm"><Field label="Admin notification email"><Text type="email" value={form.admin_email || ''} onChange={v=>set('admin_email', v)} /></Field><Field label="Confirmation subject"><Text value={form.confirmation_subject || ''} onChange={v=>set('confirmation_subject', v)} /></Field><Field label="Confirmation email body"><Textarea rows={4} value={form.confirmation_body || ''} onChange={v=>set('confirmation_body', v)} /></Field><Field label="Reminder email body"><Textarea rows={4} value={form.reminder_body || ''} onChange={v=>set('reminder_body', v)} /></Field></div>; }
function LeadForm({ form, setForm }) { const set=(k,v)=>setForm(f=>({ ...f, [k]:v })); return <div className="settingsForm"><Field label="Name"><Text value={form.name || ''} onChange={v=>set('name', v)} /></Field><Field label="Email"><Text type="email" value={form.email || ''} onChange={v=>set('email', v)} /></Field><Field label="Product ID"><Text value={form.product_id || ''} onChange={v=>set('product_id', v)} /></Field><Field label="Status"><Select value={form.status} onChange={v=>set('status', v)}><option>new</option><option>registered</option><option>contacted</option><option>paid</option><option>closed</option></Select></Field><Field label="Paid"><Check checked={form.paid} onChange={v=>set('paid', v)} /></Field></div>; }
function KnowledgeForm({ form, setForm }) { const set=(k,v)=>setForm(f=>({ ...f, [k]:v })); return <div className="settingsForm"><Field label="Source type"><Select value={form.source_type} onChange={v=>set('source_type', v)}><option>manual</option><option>google_drive</option><option>product</option><option>service</option></Select></Field><Field label="Source ID"><Text value={form.source_id || ''} onChange={v=>set('source_id', v)} /></Field><Field label="Approved knowledge content"><Textarea rows={8} value={form.content || ''} onChange={v=>set('content', v)} /></Field></div>; }
function GenericJsonForm({ form, setForm }) { return <div className="settingsForm"><Field label="JSON row"><Textarea rows={8} value={JSON.stringify(form, null, 2)} onChange={v=>{ try { setForm(JSON.parse(v)); } catch {} }} /></Field></div>; }

function FormFor({ table, form, setForm }) {
  if (table === 'ai_settings') return <AiSettingsForm form={form} setForm={setForm} />;
  if (table === 'chat_settings') return <ChatSettingsForm form={form} setForm={setForm} />;
  if (table === 'products' || table === 'services') return <ProductServiceForm table={table} form={form} setForm={setForm} />;
  if (table === 'booking_settings') return <BookingSettingsForm form={form} setForm={setForm} />;
  if (table === 'bookings') return <BookingForm form={form} setForm={setForm} />;
  if (table === 'google_drive_widgets') return <DriveForm form={form} setForm={setForm} />;
  if (table === 'payment_settings') return <PaymentSettingsForm form={form} setForm={setForm} />;
  if (table === 'email_settings') return <EmailSettingsForm form={form} setForm={setForm} />;
  if (table === 'leads') return <LeadForm form={form} setForm={setForm} />;
  if (table === 'knowledge_base') return <KnowledgeForm form={form} setForm={setForm} />;
  return <GenericJsonForm form={form} setForm={setForm} />;
}



function ClientAuthPage({ mode='login' }) {
  const isRegister = mode === 'register';
  const [form, setForm] = useState({ name:'', company_name:'', phone:'', email:'', password:'' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const set = (k,v) => setForm(f=>({ ...f, [k]:v }));
  async function submit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = isRegister ? await registerClient(form) : await loginClient({ email: form.email, password: form.password });
      setClientToken(res.access_token);
      location.href = '/client-dashboard';
    } catch (e) {
      setError(isRegister ? 'Registration failed. The email may already be registered or the password is too short.' : 'Invalid email or password.');
    } finally { setLoading(false); }
  }
  return <div className="loginShell clientLoginShell"><form className="loginCard" onSubmit={submit}>
    <div className="loginIcon"><UserRound size={28}/></div>
    <h1>{isRegister ? 'Client Registration' : 'Client Login'}</h1>
    <p>{isRegister ? 'Create your client account. A lead record will be created for admin follow-up, and you can access your own chat-enabled dashboard.' : 'Login to your client dashboard with the chat-enabled support widget.'}</p>
    {error && <pre className="error">{error}</pre>}
    {isRegister && <><label>Name<input value={form.name} onChange={e=>set('name', e.target.value)} required autoFocus /></label><label>Company name<input value={form.company_name} onChange={e=>set('company_name', e.target.value)} /></label><label>Phone<input value={form.phone} onChange={e=>set('phone', e.target.value)} /></label></>}
    <label>Email<input type="email" value={form.email} onChange={e=>set('email', e.target.value)} required autoFocus={!isRegister} /></label>
    <label>Password<input type="password" value={form.password} onChange={e=>set('password', e.target.value)} required minLength={8} /></label>
    <button disabled={loading}>{loading ? 'Please wait...' : isRegister ? 'Create Client Account' : 'Login'}</button>
    <small>{isRegister ? <>Already registered? <a href="/client-login">Login here</a></> : <>New client? <a href="/client-register">Register here</a></>}</small>
    <small><a href="/">Back to chat homepage</a></small>
  </form></div>;
}

function ClientDashboard() {
  const [client, setClient] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [products, setProducts] = useState([]);
  const [services, setServices] = useState([]);
  const [settings, setSettings] = useState({});
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const visitorId = useVisitorId();
  useEffect(() => {
    clientMe().then(c => { setClient(c); setAuthChecked(true); }).catch(() => { setAuthChecked(true); location.href = '/client-login'; });
    getProducts().then(setProducts); getServices().then(setServices); getChatSettings().then(setSettings).catch(()=>{});
  }, []);
  function logout() { logoutClient(); location.href = '/client-login'; }
  async function submit(e) {
    e.preventDefault(); const text = input.trim(); if (!text || loading) return;
    setInput(''); setMessages(m => [...m, { role:'user', text }]); setLoading(true);
    try {
      const res = await sendChat({ message: text, visitor_id: `client:${client?.id || visitorId}`, lang: navigator.language || 'en' });
      setMessages(m => [...m, { role:'assistant', text: res.answer, products: res.products || [], sources: res.sources || [] }]);
    } catch { setMessages(m => [...m, { role:'assistant', text:'Sorry, the chat service is unavailable. Please contact info6@malriffaie.com.' }]); }
    finally { setLoading(false); }
  }
  if (!authChecked) return <div className="loginShell"><div className="loginCard"><p>Loading client dashboard...</p></div></div>;
  return <div className="clientDashboardShell">
    <aside className="clientSide"><div className="sideBrand"><div className="brandMark">AI</div><div><strong>Client Dashboard</strong><small>{client?.name || client?.email}</small></div></div><a className="clientNavLink" href="/">Homepage chat</a><button className="newChatBtn" onClick={()=>setMessages([])}>New chat</button><button className="newChatBtn" onClick={logout}>Logout</button></aside>
    <main className="clientMain"><header className="clientHeader"><div><h1>Welcome{client?.name ? `, ${client.name}` : ''}</h1><p>Your private client dashboard includes a chat-enabled support widget, product help, and service guidance.</p></div></header>
      <section className="clientCards"><div className="clientInfoCard"><h3>Client Details</h3><p><b>Email:</b> {client?.email}</p>{client?.company_name && <p><b>Company:</b> {client.company_name}</p>}{client?.phone && <p><b>Phone:</b> {client.phone}</p>}</div><div className="clientInfoCard"><h3>Quick Actions</h3><p>Ask the assistant about products, booking, service details, or document support.</p></div></section>
      <section className="clientChatWidget"><div className="widgetHeader"><h2>Support Chat</h2><span>{settings.brand_subtitle || 'AI Concierge'}</span></div><div className="widgetMessages">{!messages.length && <div className="empty smallEmpty"><h3>How can we help?</h3><p>Ask about products, services, pricing, FAQs, or booking.</p></div>}{messages.map((m,i)=><div key={i} className={`msg ${m.role}`}><p>{m.text}</p>{m.products?.length>0 && <div className="cards">{m.products.map(p=><ProductCard key={p.id} product={p}/>)}</div>}</div>)}{loading && <div className="msg assistant"><p>Thinking...</p></div>}</div><form className="widgetComposer" onSubmit={submit}><input value={input} onChange={e=>setInput(e.target.value)} placeholder="Ask your client support question..."/><button><Send size={18}/> Send</button></form></section>
      <section className="clientCards"><div className="clientInfoCard"><h3>Products</h3>{products.slice(0,5).map(p=><p key={p.id}>{p.name} - <Money value={p.price} currency={p.currency}/></p>)}</div><div className="clientInfoCard"><h3>Services</h3>{services.slice(0,5).map(s=><p key={s.id}>{s.name} - <Money value={s.price} currency={s.currency}/></p>)}</div></section>
    </main>
  </div>;
}

function LoginPage() {
  const [email, setEmail] = useState('admin@aits.cc');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await loginAdmin({ email, password });
      setAdminToken(res.access_token);
      location.reload();
    } catch (e) {
      setError('Invalid email or password.');
    } finally {
      setLoading(false);
    }
  }
  return <div className="loginShell"><form className="loginCard" onSubmit={submit}><div className="loginIcon"><Lock size={28}/></div><h1>Admin Login</h1><p>Sign in to manage products, services, bookings, settings, leads, and chat history.</p>{error && <pre className="error">{error}</pre>}<label>Email<input type="email" value={email} onChange={e=>setEmail(e.target.value)} autoFocus /></label><label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} /></label><button disabled={loading}>{loading ? 'Signing in...' : 'Login'}</button><small>Default login: admin@aits.cc. Change the password immediately after first login.</small></form></div>;
}

function ChangePasswordModal({ onClose }) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  async function submit(e) {
    e.preventDefault();
    setMessage('');
    setError('');
    if (newPassword !== confirmPassword) { setError('New passwords do not match.'); return; }
    try {
      const res = await changeAdminPassword({ current_password: currentPassword, new_password: newPassword });
      setMessage(res.message || 'Password changed successfully.');
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
    } catch (e) { setError(e.message); }
  }
  return <div className="modalBackdrop"><form className="modalCard" onSubmit={submit}><div className="adminHeader"><div><h2>Change Password</h2><p>Update the logged-in admin password.</p></div><button type="button" className="secondary" onClick={onClose}>Close</button></div>{error && <pre className="error">{error}</pre>}{message && <div className="notice">{message}</div>}<Field label="Current password"><Text type="password" value={currentPassword} onChange={setCurrentPassword}/></Field><Field label="New password"><Text type="password" value={newPassword} onChange={setNewPassword}/></Field><Field label="Confirm new password"><Text type="password" value={confirmPassword} onChange={setConfirmPassword}/></Field><div className="actions"><button><KeyRound size={16}/> Change Password</button></div></form></div>;
}

function AdminAuthGate() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  useEffect(() => { adminMe().then(() => setAuthed(true)).catch(() => { logoutAdmin(); setAuthed(false); }).finally(() => setReady(true)); }, []);
  if (!ready) return <div className="loginShell"><div className="loginCard"><p>Checking admin session...</p></div></div>;
  if (!authed) return <LoginPage />;
  return <AdminPage />;
}

function AdminPage() {
  const [tab, setTab] = useState('ai_settings'); const [rows, setRows] = useState([]); const [form, setForm] = useState(defaults.ai_settings); const [editingId, setEditingId] = useState(null); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [showPassword, setShowPassword] = useState(false);
  const settingTables = ['ai_settings','chat_settings','booking_settings','payment_settings','email_settings'];
  async function load(t=tab) { try { const data = await adminList(t); setRows(data); setError(''); if (settingTables.includes(t) && data?.[0]) { setForm({ ...(defaults[t] || {}), ...data[0] }); setEditingId(data[0].id); } else { setForm(defaults[t] || {}); setEditingId(null); } } catch(e){ setError(e.message); } }
  useEffect(()=>{ load(tab); }, [tab]);
  async function save() { try { const payload = cleanPayload(tab, form); if (editingId) await adminUpdate(tab, editingId, payload); else await adminCreate(tab, payload); setNotice('Saved successfully.'); await load(); } catch(e){ setError(e.message); } }
  function edit(row) { setEditingId(row.id); setForm({ ...(defaults[tab] || {}), ...row }); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  function addNew() { setEditingId(null); setForm(defaults[tab] || {}); }
  async function remove(id) { if(confirm('Delete row?')) { await adminDelete(tab, id); await load(); } }
  async function runTestHF() { try { setNotice('Testing Hugging Face connection...'); const payload = cleanPayload('ai_settings', form); const res = await testHuggingFace(payload); setNotice(res.ok ? 'Hugging Face connection successful.' : JSON.stringify(res)); } catch(e) { setError(e.message); } }
  async function syncDrive(id) { try { const res = await syncDriveWidget(id); setNotice(res.message || 'Sync completed.'); await load(); } catch(e){ setError(e.message); } }
  async function downloadLeads() { try { const res = await exportLeadsCsv(); const blob = new Blob([res.csv || ''], { type:'text/csv' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'leads.csv'; a.click(); URL.revokeObjectURL(url); } catch(e){ setError(e.message); } }
  return <div className="adminShell"><aside className="adminNav"><h2>Admin Dashboard</h2><p>Settings, CRUD, bookings, leads, and history.</p>{tabs.map(([key,label])=><button className={tab===key?'active':''} onClick={()=>setTab(key)} key={key}>{label}</button>)}</aside><main className="adminMain"><div className="adminHeader"><div><h1>{tabs.find(x=>x[0]===tab)?.[1]}</h1><p>{editingId ? 'Editing existing record.' : 'Create or configure a new record.'}</p></div><div className="adminTopActions"><button className="secondary" onClick={()=>setShowPassword(true)}><KeyRound size={16}/> Change Password</button><button className="secondary" onClick={()=>{ logoutAdmin(); location.reload(); }}><LogOut size={16}/> Logout</button><button className="secondary" onClick={addNew}><Plus size={16}/> New</button></div></div>{showPassword && <ChangePasswordModal onClose={()=>setShowPassword(false)} />}{error && <pre className="error">{error}</pre>}{notice && <div className="notice">{notice}</div>}<section className="panel"><FormFor table={tab} form={form} setForm={setForm}/><div className="actions"><button onClick={save}><Save size={16}/> {editingId ? 'Update' : 'Create'}</button>{tab==='ai_settings' && <button className="secondary" onClick={runTestHF}><TestTube size={16}/> Test Saved AI Connection</button>}{tab==='leads' && <button className="secondary" onClick={downloadLeads}><Download size={16}/> Export CSV</button>}</div></section><section className="panel"><h3>Existing Records</h3><div className="tableWrap"><table><thead><tr>{Object.keys(rows[0]||{id:'', name:'', created_at:''}).map(k=><th key={k}>{k}</th>)}<th>Actions</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}>{Object.keys(rows[0]||{}).map(k=><td key={k}>{typeof r[k]==='object'?JSON.stringify(r[k]):String(r[k] ?? '')}</td>)}<td className="rowActions"><button className="small" onClick={()=>edit(r)}><Pencil size={14}/> Edit</button>{tab==='google_drive_widgets' && <button className="small" onClick={()=>syncDrive(r.id)}><RefreshCw size={14}/> Sync</button>}<button className="small danger" onClick={()=>remove(r.id)}><Trash2 size={14}/> Delete</button></td></tr>)}</tbody></table></div></section></main></div>;
}

function App(){ const path = location.pathname; if (path.startsWith('/admin')) return <AdminAuthGate/>; if (path.startsWith('/client-register')) return <ClientAuthPage mode="register"/>; if (path.startsWith('/client-login')) return <ClientAuthPage mode="login"/>; if (path.startsWith('/client-dashboard')) return <ClientDashboard/>; return <ChatPage/>; }

createRoot(document.getElementById('root')).render(<App/>);
