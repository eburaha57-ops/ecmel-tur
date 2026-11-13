#!/usr/bin/env python3
"""Public site server for Ecmel Turizm. Run with: python3 site_server.py"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote, urlencode
import hashlib, html, json, os, re, sqlite3, time, threading, secrets, mimetypes, base64, ipaddress
import urllib.request, urllib.error
from datetime import datetime, timedelta, time as datetime_time

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
UPLOADS = ROOT / 'assets' / 'uploads'
DB = DATA / 'ecmel-cms.sqlite3'
DATA.mkdir(exist_ok=True); UPLOADS.mkdir(parents=True, exist_ok=True)
try: os.chmod(DATA,0o700)
except OSError: pass
TOUR_PAGES = {
    'umre':'Umre','hac':'Hac',
    'ozbekistan-turu':'Kültür Turları','endulus-turu':'Kültür Turları','kudus-turu':'Kültür Turları',
    'misir-turu':'Kültür Turları','dubai-turu':'Yurtdışı Turlar','balkan-turu':'Kültür Turları','fas-turu':'Kültür Turları','bosna-turu':'Kültür Turları',
    'edirne-gezisi':'Yurtiçi · Günübirlik','cubuk-golunden-mudurnuya':'Yurtiçi · Günübirlik',
    'assos-turu':'Yurtiçi · Konaklamalı','kapadokya-turu':'Yurtiçi · Konaklamalı','obam-termal':'Yurtiçi · Kaplıca'
}
TOUR_CATEGORY_PAGES = {
    'turlar':'Tur Kategori Sayfaları','kultur-turlari':'Tur Kategori Sayfaları','yurtdisi-turlar':'Tur Kategori Sayfaları',
    'yurtici-turlar':'Tur Kategori Sayfaları','gunubirlik-turlar':'Tur Kategori Sayfaları',
    'konaklamali-turlar':'Tur Kategori Sayfaları','kaplica-turlari':'Tur Kategori Sayfaları'
}
TOUR_PAGE_SLUGS=set(TOUR_PAGES)|set(TOUR_CATEGORY_PAGES)
SERVICE_PAGE_SLUGS={'hizmetler','vize','ucak-bileti','otel','banka-hesaplari'}
def page_group(slug):
    if slug in TOUR_PAGE_SLUGS:return 'tours'
    if slug in SERVICE_PAGE_SLUGS:return 'services'
    return 'other'

def load_env_file():
    env_path=ROOT/'.env'
    if not env_path.exists(): return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key,value=line.split('=',1); key=key.strip(); value=value.strip().strip('"').strip("'")
        if key and key not in os.environ: os.environ[key]=value

load_env_file()
_schema_ready=False
_schema_lock=threading.Lock()
_analytics_last_prune=0
_exchange_rates_cache=None
_login_attempts={}
ADMIN_IDLE_TIMEOUT_SECONDS=30*60

def analytics_host(value):
    """Return a canonical public hostname, excluding local and preview hosts."""
    raw=str(value or '').strip()
    if not raw:return ''
    parsed=urlparse(raw if '://' in raw else '//' + raw)
    host=(parsed.hostname or '').lower().rstrip('.')
    if host.startswith('www.'):host=host[4:]
    if not host or host in {'localhost','localhost.localdomain'} or host.endswith(('.local','.test','.localhost')):return ''
    try:
        if not ipaddress.ip_address(host).is_global:return ''
    except ValueError:
        if '.' not in host:return ''
    return host

def configured_analytics_host(db):
    row=db.execute("SELECT value FROM settings WHERE key='seo_json'").fetchone()
    try:
        seo=json.loads(row['value']) if row else {}
        return analytics_host(seo.get('site_url',''))
    except (TypeError,ValueError,AttributeError):
        return ''

class AiError(Exception):
    def __init__(self,message,status=502): super().__init__(message); self.status=status
_ai_calls={}
AI_TOUR_PROMPT = """Bu bir seyahat acentesinin tur broşürü. İçindeki bilgileri aşağıdaki JSON biçiminde çıkar. SADECE JSON döndür, açıklama yazma.
Kurallar: Broşürde olmayan hiçbir bilgiyi uydurma; bilinmeyen alanı "" (metin) veya [] (liste) bırak. Tarihler YYYY-MM-DD. Para birimi yalnızca USD, EUR, TRY veya SAR. Fiyat sayı olsun (binlik ayırıcı yok). Metinler Türkçe ve broşüre sadık olsun.
{
 "title": "tur adı",
 "category": "Umre | Hac | Kültür Turları | Yurtdışı Turlar | Yurtiçi · Günübirlik | Yurtiçi · Konaklamalı | Yurtiçi · Kaplıca seçeneklerinden biri",
 "description": "2-3 cümlelik kısa tanıtım",
 "flight_info": "ulaşım ve uçuş bilgisi",
 "content": "günlük program akışı, her gün ayrı satırda",
 "included_services": "fiyata dahil olanlar, her biri ayrı satırda",
 "excluded_services": "fiyata dahil olmayanlar, her biri ayrı satırda",
 "price_details": "çocuk/tek kişi farkı vb. ek fiyat notları",
 "departures": [
  {"event_name": "varsa etkinlik adı", "outbound_date": "YYYY-MM-DD",
   "durations": [
    {"nights": 7, "days": 8, "return_date": "YYYY-MM-DD veya boş",
     "stays": [{"city": "Mekke", "hotel": "otel adı veya boş", "nights": 4}],
     "rooms": [{"room": "2 kişilik oda", "amount": 1500, "currency": "USD"}]}
   ]}
 ]
}
Aynı hareket tarihinde birden fazla süre (örn. 9 gece ve 13 gece) varsa her birini ayrı durations öğesi yap."""
def ai_read_brochure(mime,b64):
    key=os.environ.get('ANTHROPIC_API_KEY','').strip()
    if not key: raise AiError('Yapay zekâ henüz etkin değil: sunucuya ANTHROPIC_API_KEY eklenmemiş.',503)
    today=time.strftime('%Y-%m-%d'); limit=int(os.environ.get('ECMEL_AI_DAILY_LIMIT','30') or 30)
    if _ai_calls.get(today,0)>=limit: raise AiError('Günlük broşür okuma sınırına ulaşıldı. Yarın yeniden deneyin.',429)
    block={'type':'document','source':{'type':'base64','media_type':mime,'data':b64}} if mime=='application/pdf' else {'type':'image','source':{'type':'base64','media_type':mime,'data':b64}}
    payload={'model':os.environ.get('ECMEL_AI_MODEL','claude-sonnet-5-5'),'max_tokens':6000,'messages':[{'role':'user','content':[block,{'type':'text','text':AI_TOUR_PROMPT}]}]}
    base=os.environ.get('ECMEL_AI_BASE','https://api.anthropic.com').rstrip('/')
    req=urllib.request.Request(base+'/v1/messages',data=json.dumps(payload).encode(),headers={'content-type':'application/json','x-api-key':key,'anthropic-version':'2023-06-01'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise AiError('Yapay zekâ servisi hata verdi (%s). API anahtarını ve bakiyeyi kontrol edin.'%e.code,502)
    except Exception:
        raise AiError('Yapay zekâ servisine ulaşılamadı. Lütfen tekrar deneyin.',502)
    _ai_calls[today]=_ai_calls.get(today,0)+1
    text=''.join(c.get('text','') for c in out.get('content',[]) if c.get('type')=='text')
    m=re.search(r'\{.*\}',text,re.S)
    try: data=json.loads(m.group(0)) if m else None
    except Exception: data=None
    if not isinstance(data,dict): raise AiError('Broşürden bilgi okunamadı. Daha net bir dosya deneyin.',422)
    return data

class Database:
    """Small SQLite/PostgreSQL adapter used by the existing CMS queries."""
    def __init__(self, connection, postgres=False): self.connection=connection; self.postgres=postgres
    def execute(self, sql, params=()):
        # psycopg uses percent-based placeholders even when a statement only
        # has positional parameters elsewhere. Escape SQL wildcard literals
        # before translating our SQLite-style ``?`` placeholders.
        if self.postgres: sql=sql.replace('%','%%').replace('?', '%s')
        return self.connection.execute(sql, params)
    def executescript(self, script):
        if self.postgres:
            for statement in script.split(';'):
                if statement.strip(): self.connection.execute(statement)
        else: self.connection.executescript(script)
    def commit(self): return self.connection.commit()
    def close(self): return self.connection.close()

def connect():
    global _schema_ready
    dsn=os.environ.get('DATABASE_URL','').strip()
    if dsn:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError('Neon kullanmak için psycopg kurulmalı: python3 -m pip install -r requirements.txt') from error
        # Neon requires encrypted connections; pooled URLs are recommended for web apps.
        separator='&' if '?' in dsn else '?'
        if 'sslmode=' not in dsn: dsn += separator+'sslmode=require'
        db=Database(psycopg.connect(dsn,connect_timeout=10,row_factory=dict_row),postgres=True)
    else:
        connection=sqlite3.connect(DB,timeout=20); connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        db=Database(connection)
    if not _schema_ready:
        with _schema_lock:
            if not _schema_ready:
                if db.postgres:
                    db.executescript('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS pages (slug TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', media TEXT NOT NULL DEFAULT '', video TEXT NOT NULL DEFAULT '', active BOOLEAN NOT NULL DEFAULT TRUE, status TEXT NOT NULL DEFAULT 'published', content TEXT NOT NULL DEFAULT '', group_key TEXT NOT NULL DEFAULT 'other');
                    CREATE TABLE IF NOT EXISTS tours (id BIGSERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', date TEXT NOT NULL DEFAULT '', price TEXT NOT NULL DEFAULT '', media TEXT NOT NULL DEFAULT '', video TEXT NOT NULL DEFAULT '', active BOOLEAN NOT NULL DEFAULT TRUE, status TEXT NOT NULL DEFAULT 'published', content TEXT NOT NULL DEFAULT '', static_page_slug TEXT UNIQUE, record_type TEXT NOT NULL DEFAULT 'tour', duration TEXT NOT NULL DEFAULT '', outbound_date TEXT NOT NULL DEFAULT '', return_date TEXT NOT NULL DEFAULT '', flight_info TEXT NOT NULL DEFAULT '', accommodation TEXT NOT NULL DEFAULT '', price_details TEXT NOT NULL DEFAULT '', included_services TEXT NOT NULL DEFAULT '', excluded_services TEXT NOT NULL DEFAULT '', price_options TEXT NOT NULL DEFAULT '[]', brochure TEXT NOT NULL DEFAULT '');
                    CREATE TABLE IF NOT EXISTS analytics_visits (id BIGSERIAL PRIMARY KEY, visitor_hash TEXT NOT NULL, page TEXT NOT NULL, visited_at BIGINT NOT NULL);
                    CREATE TABLE IF NOT EXISTS analytics_active (visitor_hash TEXT PRIMARY KEY, last_seen BIGINT NOT NULL);
                    CREATE INDEX IF NOT EXISTS analytics_visits_time_idx ON analytics_visits(visited_at);
                    CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires BIGINT NOT NULL); CREATE TABLE IF NOT EXISTS guest_reviews (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, trip TEXT NOT NULL DEFAULT '', review TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at BIGINT NOT NULL); CREATE TABLE IF NOT EXISTS contact_messages (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', message TEXT NOT NULL, created_at BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'new');''')
                    for table,col,definition in [('pages','active','BOOLEAN NOT NULL DEFAULT TRUE'),('pages','status',"TEXT NOT NULL DEFAULT 'published'"),('pages','content',"TEXT NOT NULL DEFAULT ''"),('pages','group_key',"TEXT NOT NULL DEFAULT 'other'"),('tours','active','BOOLEAN NOT NULL DEFAULT TRUE'),('tours','status',"TEXT NOT NULL DEFAULT 'published'"),('tours','content',"TEXT NOT NULL DEFAULT ''"),('tours','static_page_slug','TEXT UNIQUE'),('tours','record_type',"TEXT NOT NULL DEFAULT 'tour'"),('tours','duration',"TEXT NOT NULL DEFAULT ''"),('tours','outbound_date',"TEXT NOT NULL DEFAULT ''"),('tours','return_date',"TEXT NOT NULL DEFAULT ''"),('tours','flight_info',"TEXT NOT NULL DEFAULT ''"),('tours','accommodation',"TEXT NOT NULL DEFAULT ''"),('tours','price_details',"TEXT NOT NULL DEFAULT ''"),('tours','included_services',"TEXT NOT NULL DEFAULT ''"),('tours','excluded_services',"TEXT NOT NULL DEFAULT ''"),('tours','price_options',"TEXT NOT NULL DEFAULT '[]'"),('tours','brochure',"TEXT NOT NULL DEFAULT ''"),('analytics_visits','source_host',"TEXT NOT NULL DEFAULT ''"),('analytics_active','source_host',"TEXT NOT NULL DEFAULT ''")]: db.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {definition}')
                else:
                    db.executescript('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS pages (slug TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', media TEXT NOT NULL DEFAULT '', video TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'published', content TEXT NOT NULL DEFAULT '', group_key TEXT NOT NULL DEFAULT 'other');
                    CREATE TABLE IF NOT EXISTS tours (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', date TEXT NOT NULL DEFAULT '', price TEXT NOT NULL DEFAULT '', media TEXT NOT NULL DEFAULT '', video TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'published', content TEXT NOT NULL DEFAULT '', static_page_slug TEXT UNIQUE, record_type TEXT NOT NULL DEFAULT 'tour', duration TEXT NOT NULL DEFAULT '', outbound_date TEXT NOT NULL DEFAULT '', return_date TEXT NOT NULL DEFAULT '', flight_info TEXT NOT NULL DEFAULT '', accommodation TEXT NOT NULL DEFAULT '', price_details TEXT NOT NULL DEFAULT '', included_services TEXT NOT NULL DEFAULT '', excluded_services TEXT NOT NULL DEFAULT '', price_options TEXT NOT NULL DEFAULT '[]', brochure TEXT NOT NULL DEFAULT '');
                    CREATE TABLE IF NOT EXISTS analytics_visits (id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_hash TEXT NOT NULL, page TEXT NOT NULL, visited_at INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS analytics_active (visitor_hash TEXT PRIMARY KEY, last_seen INTEGER NOT NULL);
                    CREATE INDEX IF NOT EXISTS analytics_visits_time_idx ON analytics_visits(visited_at);
                    CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS guest_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, trip TEXT NOT NULL DEFAULT '', review TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS contact_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', message TEXT NOT NULL, created_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'new');''')
                    for table,col,definition in [('pages','active','INTEGER NOT NULL DEFAULT 1'),('pages','status',"TEXT NOT NULL DEFAULT 'published'"),('pages','content',"TEXT NOT NULL DEFAULT ''"),('pages','group_key',"TEXT NOT NULL DEFAULT 'other'"),('tours','active','INTEGER NOT NULL DEFAULT 1'),('tours','status',"TEXT NOT NULL DEFAULT 'published'"),('tours','content',"TEXT NOT NULL DEFAULT ''"),('tours','static_page_slug','TEXT'),('tours','record_type',"TEXT NOT NULL DEFAULT 'tour'"),('tours','duration',"TEXT NOT NULL DEFAULT ''"),('tours','outbound_date',"TEXT NOT NULL DEFAULT ''"),('tours','return_date',"TEXT NOT NULL DEFAULT ''"),('tours','flight_info',"TEXT NOT NULL DEFAULT ''"),('tours','accommodation',"TEXT NOT NULL DEFAULT ''"),('tours','price_details',"TEXT NOT NULL DEFAULT ''"),('tours','included_services',"TEXT NOT NULL DEFAULT ''"),('tours','excluded_services',"TEXT NOT NULL DEFAULT ''"),('tours','price_options',"TEXT NOT NULL DEFAULT '[]'"),('tours','brochure',"TEXT NOT NULL DEFAULT ''")]:
                        try: db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
                        except sqlite3.OperationalError: pass
                    try: db.execute('CREATE UNIQUE INDEX IF NOT EXISTS tours_static_page_slug_idx ON tours(static_page_slug)')
                    except sqlite3.OperationalError: pass
                    for table in ('analytics_visits','analytics_active'):
                        columns={row['name'] for row in db.execute(f'PRAGMA table_info({table})').fetchall()}
                        if 'source_host' not in columns:db.execute(f"ALTER TABLE {table} ADD COLUMN source_host TEXT NOT NULL DEFAULT ''")
                db.commit(); _schema_ready=True
    if not db.postgres:
        try: os.chmod(DB,0o600)
        except OSError: pass
    return db

def purged_keys(db):
    row=db.execute("SELECT value FROM settings WHERE key='purged_json'").fetchone()
    try:return set(json.loads(row['value'])) if row else set()
    except Exception:return set()

def add_purged(db,keys):
    merged=sorted(purged_keys(db)|set(keys))
    db.execute("INSERT INTO settings(key,value) VALUES('purged_json',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(merged),))

def remove_from_menus(db,slug):
    targets=(f'pages/{slug}.html',f'{slug}.html',slug)
    for key in ('menu_json','footer_menu_json','top_menu_json'):
        row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        if row:
            try:
                items=[i for i in json.loads(row['value']) if i.get('href') not in targets]
                db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(items,ensure_ascii=False),key))
            except Exception:pass
    trrow=db.execute("SELECT value FROM settings WHERE key='translations_json'").fetchone()
    if trrow:
        try:
            translations=json.loads(trrow['value'])
            for lang in translations.values():
                lang.get('pages',{}).pop(slug,None)
                for group in lang.get('menus',{}).values():group[:]=[i for i in group if i.get('href') not in targets]
            db.execute("UPDATE settings SET value=? WHERE key='translations_json'",(json.dumps(translations,ensure_ascii=False),))
        except Exception:pass

def seed_pages(db):
    purged=purged_keys(db)
    for f in sorted((ROOT/'pages').glob('*.html')):
        if f'page:{f.stem}' in purged:continue
        raw=f.read_text(encoding='utf-8',errors='ignore')
        title=re.search(r'<h1[^>]*>(.*?)</h1>',raw,re.S)
        title=re.sub('<.*?>','',title.group(1)).strip() if title else f.stem.replace('-',' ').title()
        desc=re.search(r'<meta name="description" content="([^"]*)"',raw)
        desc=html.unescape(desc.group(1)) if desc else ''
        db.execute('INSERT INTO pages(slug,title,description,group_key) VALUES(?,?,?,?) ON CONFLICT(slug) DO NOTHING',(f.stem,title,desc,page_group(f.stem)))
        if page_group(f.stem)!='other':db.execute('UPDATE pages SET group_key=? WHERE slug=? AND group_key=?',(page_group(f.stem),f.stem,'other'))
    db.execute("INSERT INTO pages(slug,title,description,group_key) VALUES('home','Ana Sayfa','Program seçiminizden dönüş gününüze kadar, Ecmel Turizm’in deneyimli ekibi her aşamada yanınızda.','other') ON CONFLICT(slug) DO NOTHING")
    db.commit()

def seed_tours_from_pages(db):
    purged=purged_keys(db)
    all_pages={**TOUR_PAGES,**TOUR_CATEGORY_PAGES}
    for slug,category in all_pages.items():
        page=db.execute('SELECT * FROM pages WHERE slug=?',(slug,)).fetchone()
        if not page or f'page:{slug}' in purged: continue
        ascii_slug=__import__('unicodedata').normalize('NFKD',slug).encode('ascii','ignore').decode().lower()
        try:
            record_type='category' if slug in TOUR_CATEGORY_PAGES else 'tour'
            db.execute('''INSERT INTO tours(slug,title,category,description,date,price,media,video,active,status,content,static_page_slug,record_type)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(static_page_slug) DO NOTHING''',
                ('static-'+ascii_slug,page['title'],category,page['description'],'','','','',page['active'],page['status'],page['content'],slug,record_type))
        except Exception as error:
            if error.__class__.__name__ not in ('UniqueViolation','IntegrityError'): raise
    db.commit()

def seed_admin_defaults(db):
    primary=[{'label':'Umre','href':'pages/umre.html'},{'label':'Hac','href':'pages/hac.html'},
      {'label':'Turlar','href':'pages/turlar.html'},{'label':'Kültür turları','href':'pages/kultur-turlari.html','parent':'Turlar'},
      {'label':'Yurtdışı turlar','href':'pages/yurtdisi-turlar.html','parent':'Turlar'},{'label':'Yurtiçi turlar','href':'pages/yurtici-turlar.html','parent':'Turlar'},
      {'label':'Hizmetler','href':'pages/hizmetler.html'},{'label':'Vize danışmanlığı','href':'pages/vize.html','parent':'Hizmetler'},
      {'label':'Uçak bileti','href':'pages/ucak-bileti.html','parent':'Hizmetler'},{'label':'Otel ve konaklama','href':'pages/otel.html','parent':'Hizmetler'},
      {'label':'Kurumsal','href':'pages/hakkimizda.html'},{'label':'Hakkımızda','href':'pages/hakkimizda.html','parent':'Kurumsal'},
      {'label':'Ekibimiz','href':'pages/ekibimiz.html','parent':'Kurumsal'},{'label':'İletişim','href':'pages/iletisim.html'}]
    footer=[{'label':'Umre','href':'pages/umre.html'},{'label':'Hac','href':'pages/hac.html'},
      {'label':'Yurtdışı turlar','href':'pages/yurtdisi-turlar.html'},{'label':'Yurtiçi turlar','href':'pages/yurtici-turlar.html'},
      {'label':'Vize','href':'pages/vize.html'},{'label':'Uçak bileti','href':'pages/ucak-bileti.html'},
      {'label':'Otel','href':'pages/otel.html'},{'label':'Yardım merkezi','href':'pages/sss.html'}]
    top=[{'label':'0212 635 35 52','href':'tel:+902126353552'},{'label':'info@ecmeltur.com','href':'mailto:info@ecmeltur.com'},{'label':'WhatsApp ↗','href':'https://wa.me/902126353552'}]
    defaults={'site_name':'Ecmel Turizm','phone':'0212 635 35 52','email':'info@ecmeltur.com',
      'address':'Kayabaşı Mah. Adnan Menderes Bulvarı, Kuzey Yakası Ofisleri, A1 Blok K:2 D:17, Başakşehir / İstanbul',
      'logo':'/assets/ecmel-logo.png','footer_logo':'/assets/ecmel-logo.png','menu_json':json.dumps(primary,ensure_ascii=False),
      'footer_menu_json':json.dumps(footer,ensure_ascii=False),'top_menu_json':json.dumps(top,ensure_ascii=False),'supported_languages':'["tr","en","ar"]',
      'site_language':'tr','translations_json':'{}','module_settings_json':json.dumps({'reviews':True,'analytics':True,'currency':True,'contact':True,'whatsapp':True,'blog':True,'booking':False}),
      'telegram':'','map_embed_url':'','google_analytics_id':'','webmaster_verification':'','recaptcha_site_key':'','recaptcha_enabled':'false',
      'seo_json':json.dumps({'site_url':'','defaults':{},'pages':{}},ensure_ascii=False),
      'integrations_json':json.dumps({'rate_provider':'open-er-api','rate_endpoint':'https://open.er-api.com/v6/latest/USD','base_currency':'USD','rate_cache_hours':12}),
      'maintenance_mode':'false','maintenance_message':'Web sitemiz kısa süre içinde yeniden hizmetinizde olacak. Ekibimiz sizin için çalışıyor.',
      'home_sections_json':'["hero","trust-strip","programlar","vize","hizmetler","hakkimizda","rehber","yorumlar","iletisim"]'}
    for key,value in defaults.items():db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING',(key,value))
    # Replace only known placeholder copy; keep any administrator-written text intact.
    page_copy={
      'umre':'Yayınlanan umre programlarını tarih, gece ve gün süresi, oda tipi ve kişi başı fiyat seçenekleriyle inceleyin. Size uygun programı seçip ekibimizden ayrıntı alın.',
      'hac':'Hac programlarını dönem, konaklama ve ulaşım ayrıntılarıyla inceleyin. Resmî tarihler ve kontenjan netleştikçe program bilgileri güncellenir.'
    }
    for slug,description in page_copy.items():
        row=db.execute('SELECT description FROM pages WHERE slug=?',(slug,)).fetchone()
        if row and any(token in str(row['description'] or '').lower() for token in ('sunulacak','burada paylaşılacak')):
            db.execute('UPDATE pages SET description=? WHERE slug=?',(description,slug))
    # Import verified company profile material into CMS only when an editor has
    # not already written the page. Text and cards are escaped by cms-public.js.
    profile_marker=db.execute("SELECT value FROM settings WHERE key='migration_ecmel_profile_v1'").fetchone()
    if not profile_marker:
        profile_pages={
          'hakkimizda':{'format':'ecmel-page-v1','text':'Ecmel Turizm, 2008 yılında İstanbul Fatih’te kuruldu. Kurucu ortaklarımız ilahiyat mezunu ve hac-umre organizasyonlarında uzun yıllara dayanan deneyime sahiptir. A Grubu seyahat acentası ve IATA üyeliğiyle hac, umre, kültür ve yurt dışı turlarının yanı sıra vize, uçak bileti ve konaklama süreçlerinde misafirlerimize destek veriyoruz. Ofisimiz bugün Başakşehir’dedir. Program kapsamı ve güncel koşullar her tur sayfasında ayrıca belirtilir.'},
          'ekibimiz':{'format':'ecmel-page-v1','text':'Ecmel Turizm, 2008 yılında Fatih’te; tamamı ilahiyat mezunu ve hac-umre alanında en az 20 yıllık deneyime sahip beş ortak tarafından kuruldu. Şirketimiz A Grubu Seyahat Acentası ve IATA belgeleriyle faaliyet gösteriyor.','cards':[
            {'title':'İsmet Sezer','description':'Şirket Ortağı / Genel Müdür'},
            {'title':'Cevdet Yıldırım','description':'Şirket Ortağı / Operasyon Sorumlusu'},
            {'title':'Erol Papakçı','description':'Şirket Ortağı / Operasyon Sorumlusu'},
            {'title':'Adnan Ekinci','description':'Şirket Ortağı / Bilgi İşlem Sorumlusu'},
            {'title':'Erhan Doğan','description':'Şirket Ortağı / Tur Operatörü'}]},
          'belgelerimiz':{'format':'ecmel-page-v1','text':'Ecmel Turizm’in kurumsal yetkinlikleri; seyahat acentası faaliyetleri ve havayolu sektöründeki üyelik bilgileriyle desteklenir. Belge numaraları ve geçerlilik tarihleri, doğrulanmış belge görselleri yönetim paneline yüklendiğinde burada paylaşılır.','cards':[
            {'title':'A Grubu Seyahat Acentası','description':'Ecmel Turizm, kendi resmî sitesinde A Grubu seyahat acentası olarak hizmet verdiğini beyan eder.'},
            {'title':'IATA Üyeliği','description':'Ecmel Turizm, kendi resmî sitesinde IATA üyeliğini belirtir.'}]}
        }
        for slug,model in profile_pages.items():
            exists=db.execute('SELECT content FROM pages WHERE slug=?',(slug,)).fetchone()
            if exists and not str(exists['content'] or '').strip():
                db.execute('UPDATE pages SET content=? WHERE slug=?',(json.dumps(model,ensure_ascii=False),slug))
        db.execute("INSERT INTO settings(key,value) VALUES('migration_ecmel_profile_v1','done') ON CONFLICT(key) DO NOTHING")
    team_row=db.execute("SELECT content FROM pages WHERE slug='ekibimiz'").fetchone()
    if team_row:
        try: team_model=json.loads(team_row['content'] or '{}')
        except (TypeError,ValueError): team_model={}
        changed=False
        if isinstance(team_model,dict) and team_model.get('format')=='ecmel-page-v1':
            team_text=str(team_model.get('text',''))
            if '\n\nErhan Doğan,' in team_text:
                team_model['text']=team_text.split('\n\nErhan Doğan,',1)[0].rstrip()
            changed=changed or team_model.get('text')!=team_text
            for member in team_model.get('cards',[]):
                if member.get('title')=='Erhan Doğan' and '\n' in str(member.get('description','')):
                    member['description']=str(member['description']).split('\n',1)[0].strip(); changed=True
            if changed:db.execute("UPDATE pages SET content=? WHERE slug='ekibimiz'",(json.dumps(team_model,ensure_ascii=False),))

    # Publish the user's verified 8 November 2026 Umrah brochure as a real
    # programme with duration and room-price variants, not as a generic page.
    umre_slug='8-kasim-2026-ara-tatil-umresi'
    if not db.execute("SELECT 1 FROM tours WHERE slug=? OR (category='Umre' AND outbound_date='2026-11-08' AND active=TRUE AND status='published')",(umre_slug,)).fetchone():
        variants=[]
        for nights,days,return_date,prices in [
          (9,10,'2026-11-17',[('2 kişilik oda',1525),('3 kişilik oda',1475),('4 kişilik oda',1425)]),
          (13,14,'2026-11-21',[('2 kişilik oda',1625),('3 kişilik oda',1525),('4 kişilik oda',1475)])]:
            for room,amount in prices:
                variants.append({'event_name':'8 Kasım 2026 Ara Tatil Umresi','event_outbound_date':'2026-11-08','event_return_date':return_date,'nights':nights,'days':days,'room':room,'amount':amount,'currency':'USD','label':f'{nights} gece / {days} gün · {room}'})
        db.execute('''INSERT INTO tours(slug,title,category,description,date,price,media,active,status,content,record_type,duration,outbound_date,return_date,flight_info,accommodation,price_details,included_services,excluded_services,price_options,brochure)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(slug) DO NOTHING''',(
          umre_slug,'8 Kasım 2026 Ara Tatil Umresi','Umre',
          '8 Kasım 2026 hareketli ekonomik umre programı. 9 gece / 10 gün ve 13 gece / 14 gün seçenekleri; oda paylaşımına göre kişi başı fiyatlar değişir. Kontenjan ve güncel seyahat koşullarını kayıt öncesinde ekibimizle teyit edin.',
          '8 Kasım – 17 veya 21 Kasım 2026','', 'assets/mecca-hero.jpg',True,'published','', 'tour','9 gece / 10 gün veya 13 gece / 14 gün',
          '2026-11-08','',
          'Suudi Arabistan Havayolları · 8 Kasım İstanbul–Cidde 15:25 · dönüş seçilen süreye göre Medine–İstanbul 08:40 (17 veya 21 Kasım).',
          '13 gece / 14 gün seçeneği: Mekke Cevhera Tower (10 gece, yaklaşık 1.500 m, yakın servis); Medine Nusuk Madine (3 gece, yaklaşık 300 m). Sabah ve akşam yemekleri. 9 gece / 10 gün seçeneğinin otel-gece dağılımını kayıt öncesinde ekibimizden teyit edin.',
          'Broşürde yer alan kişi başı USD fiyatları: 9 gece / 10 gün: 2 kişilik 1.525 USD, 3 kişilik 1.475 USD, 4 kişilik 1.425 USD. 13 gece / 14 gün: 2 kişilik 1.625 USD, 3 kişilik 1.525 USD, 4 kişilik 1.475 USD.',
          'Broşürde belirtilen Suudi Arabistan Havayolları uçuşu, otel konaklaması ve sabah-akşam yemekleri.',
          '',json.dumps(variants,ensure_ascii=False),''))
    # Retire only the known placeholder record; retain it in admin as a draft.
    stale_umre=db.execute("SELECT id,description,price_options,duration,outbound_date,return_date FROM tours WHERE static_page_slug='umre' AND slug='static-umre'").fetchone()
    if stale_umre and any(term in str(stale_umre['description'] or '').lower() for term in ('sunulacak','burada paylaşılacak')) and str(stale_umre['price_options'] or '[]') in ('','[]') and not stale_umre['duration'] and not stale_umre['outbound_date'] and not stale_umre['return_date']:
        db.execute("UPDATE tours SET active=FALSE,status='draft',date='',price='' WHERE id=?",(stale_umre['id'],))
    # One-time migration for the requested navigation and overseas tour regrouping.
    marker=db.execute("SELECT value FROM settings WHERE key='migration_culture_kudus_v1'").fetchone()
    if not marker:
        db.execute("UPDATE tours SET category='Kültür Turları' WHERE category='Yurtdışı Turlar' AND LOWER(slug) NOT LIKE '%dubai%' AND LOWER(title) NOT LIKE '%dubai%'")
        menu_row=db.execute("SELECT value FROM settings WHERE key='menu_json'").fetchone()
        try: menu=json.loads(menu_row['value']) if menu_row else []
        except (TypeError,ValueError): menu=[]
        if isinstance(menu,list):
            labels={'Kültür turları':'Kültür Turları','Yurtdışı turlar':'Yurtdışı Turlar','Yurtiçi turlar':'Yurtiçi Turlar','Vize danışmanlığı':'Vize Danışmanlığı','Uçak bileti':'Uçak Bileti','Otel ve konaklama':'Otel ve Konaklama'}
            for item in menu:
                if isinstance(item,dict) and item.get('label') in labels:item['label']=labels[item['label']]
            if not any(isinstance(item,dict) and item.get('href')=='pages/kudus-turu.html' for item in menu):
                insert_at=next((i+1 for i,item in enumerate(menu) if isinstance(item,dict) and item.get('href')=='pages/hac.html'),len(menu))
                menu.insert(insert_at,{'label':'Kudüs Turu','href':'pages/kudus-turu.html'})
            db.execute("UPDATE settings SET value=? WHERE key='menu_json'",(json.dumps(menu,ensure_ascii=False),))
        translation_row=db.execute("SELECT value FROM settings WHERE key='translations_json'").fetchone()
        try: translations=json.loads(translation_row['value']) if translation_row else {}
        except (TypeError,ValueError): translations={}
        changed=False
        for code,label in [('en','Jerusalem Tour'),('ar','رحلة القدس')]:
            locale=translations.get(code,{})
            localized_menu=locale.get('menus',{}).get('primary') if isinstance(locale,dict) else None
            if isinstance(localized_menu,list) and not any(isinstance(item,dict) and item.get('href')=='pages/kudus-turu.html' for item in localized_menu):
                insert_at=next((i+1 for i,item in enumerate(localized_menu) if isinstance(item,dict) and item.get('href')=='pages/hac.html'),len(localized_menu))
                localized_menu.insert(insert_at,{'label':label,'href':'pages/kudus-turu.html'})
                locale.setdefault('menus',{})['primary']=localized_menu; translations[code]=locale; changed=True
        if changed:db.execute("UPDATE settings SET value=? WHERE key='translations_json'",(json.dumps(translations,ensure_ascii=False),))
        db.execute("INSERT INTO settings(key,value) VALUES('migration_culture_kudus_v1','done') ON CONFLICT(key) DO NOTHING")
    db.commit()

def custom_page_document(page):
    title=html.escape(page['title']); description=html.escape(page['description']); media=html.escape(page['media']); content=html.escape(page['content'])
    image=f'<img src="{media}" alt="{title}" fetchpriority="high">' if media else ''
    return f'''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{description}"><title>{title} · Ecmel Turizm</title><link rel="stylesheet" href="../styles.css?v=premium-storefront-20261023b"><style>.cms-custom-page .page-banner-inner{{min-height:330px}}.cms-custom-page .page-banner-photo img{{width:100%;height:100%;object-fit:cover}}.cms-custom-content{{max-width:850px;margin:0 auto;padding:48px 0 80px;white-space:pre-wrap;line-height:1.9;color:#57675e}}</style></head><body><div class="utility-bar"><div class="shell utility-inner"><span>2008’den beri seyahat deneyimi</span><div><a href="tel:+902126353552">0212 635 35 52</a><a href="mailto:info@ecmeltur.com">info@ecmeltur.com</a></div></div></div><header class="header"><div class="shell header-inner"><a class="brand" href="../index.html"><img class="brand-logo" src="../assets/ecmel-logo.png" alt="Ecmel Turizm"></a><button class="menu-toggle" aria-label="Menüyü aç" aria-expanded="false" aria-controls="primary-nav"><span></span><span></span><span></span></button><nav class="nav" id="primary-nav"></nav><a class="header-cta" href="iletisim.html">İletişim <span>↗</span></a></div></header><main class="cms-custom-page"><section class="page-banner"><div class="page-banner-photo">{image}</div><div class="shell page-banner-inner"><div class="page-banner-copy"><p class="eyebrow">ECMEL TURİZM</p><h1>{title}</h1><p>{description}</p></div></div></section><article class="shell cms-custom-content">{content}</article></main><footer class="footer"><div class="shell"><div class="footer-main"><div><a class="brand brand-footer" href="../index.html"><img class="brand-logo" src="../assets/ecmel-logo.png" alt="Ecmel Turizm"></a><p>Hac, umre ve kültür turlarında<br>2008’den beri hizmetinizde.</p></div><div class="footer-column"><b>TURLAR</b><a href="umre.html">Umre</a><a href="hac.html">Hac</a><a href="yurtdisi-turlar.html">Yurtdışı turlar</a></div><div class="footer-column"><b>HİZMETLER</b><a href="vize.html">Vize</a><a href="otel.html">Otel</a></div><div class="footer-column footer-address"><b>ECMEL TURİZM</b><p>Kayabaşı Mah. Adnan Menderes Bulvarı, Başakşehir / İstanbul</p><a href="tel:+902126353552">0212 635 35 52</a><a href="mailto:info@ecmeltur.com">info@ecmeltur.com</a></div></div><div class="footer-bottom"><span>© 2026 Ecmel Turizm. Tüm hakları saklıdır.</span><span>A Grubu Seyahat Acentası · IATA</span></div></div></footer><script src="../cms-public.js?v=verified-tour-content-20261023i"></script><script src="../booking.js?v=request-form-r7-variants-20261023"></script><script src="../script.js?v=premium-navigation-20261023b"></script></body></html>'''

def tour_detail_document(tour):
    title=html.escape(tour['title'] or 'Tur Programı')
    category=html.escape(tour['category'] or 'Tur Programı')
    description=html.escape(tour['description'] or 'Program ayrıntıları için ekibimizle görüşün.')
    date=html.escape(tour['date'] or 'Tarih bilgisi için iletişime geçin')
    price=html.escape(tour['price'] or '')
    content=html.escape(tour['content'] or '')
    duration=html.escape(tour.get('duration') or '')
    outbound_date=html.escape(tour.get('outbound_date') or '')
    return_date=html.escape(tour.get('return_date') or '')
    flight_info=html.escape(tour.get('flight_info') or '')
    accommodation=html.escape(tour.get('accommodation') or '')
    price_details=html.escape(tour.get('price_details') or '')
    included_services=html.escape(tour.get('included_services') or '')
    excluded_services=html.escape(tour.get('excluded_services') or '')
    slug=html.escape(tour['slug'] or '')
    image_fallbacks={
        'umre':'../assets/mecca-hero.jpg','hac':'../assets/mecca-hero.jpg',
        'ozbekistan-turu':'../assets/destinations/registan-01.jpg',
        'endulus-turu':'../assets/destinations/alhambra-granada-panorama.jpg','kudus-turu':'../assets/hero-masjid-al-aqsa.jpg',
        'misir-turu':'../assets/destinations/great-pyramid-of-giza-panorama.jpg',
        'dubai-turu':'../assets/destinations/burj-khalifa-5697094559.jpg',
        'balkan-turu':'../assets/destinations/mostar-stari-most-49033180333.jpg',
        'bosna-turu':'../assets/destinations/sarajevo-old-town.jpg',
        'fas-turu':'../assets/destinations/marrakech-jemaa-el-fna-54246889027.jpg',
        'edirne-gezisi':'../assets/destinations/edirne-selimiye-mosque-in-2017-3282.jpg',
        'cubuk-golunden-mudurnuya':'../assets/destinations/cubuk-golu-panorama-ve-ahsap-iskele-goynuk-bolu-2014.jpg',
        'assos-turu':'../assets/destinations/assos-antik-kenti-temple-of-athena.jpg',
        'kapadokya-turu':'../assets/destinations/cappadocia-aerial-view-landscape.jpg',
        'obam-termal':'../assets/destinations/aga-hamam-interior-4.jpg'
    }
    media=tour['video'] or tour['media'] or image_fallbacks.get(tour.get('static_page_slug'),'')
    if not media:
        category_fallbacks={
            'Umre':'umre','Hac':'hac','Kültür Turları':'ozbekistan-turu',
            'Yurtdışı Turlar':'misir-turu','Yurtiçi · Günübirlik':'edirne-gezisi',
            'Yurtiçi · Konaklamalı':'kapadokya-turu','Yurtiçi · Kaplıca':'obam-termal'
        }
        media=image_fallbacks.get(category_fallbacks.get(tour.get('category'),''),'')
    safe_media=html.escape(media or '',quote=True)
    if safe_media and safe_media.lower().split('?')[0].endswith(('.mp4','.webm','.mov')):
        media_html=f'<video src="{safe_media}" autoplay muted loop playsinline controls></video>'
    elif safe_media:
        media_html=f'<img src="{safe_media}" alt="{title} tur programı" fetchpriority="high">'
    else:
        media_html='<div class="tour-detail-placeholder" aria-hidden="true"></div>'
    brochure_raw=str(tour.get('brochure') or '').strip()
    brochure=html.escape(brochure_raw if brochure_raw.startswith('https://') or brochure_raw.startswith('/assets/uploads/') else '',quote=True)
    brochure_html=f'<a class="tour-brochure-link" href="{brochure}" target="_blank" rel="noopener">Program broşürünü görüntüle ↗</a>' if brochure else ''
    try: price_options=json.loads(tour.get('price_options') or '[]')
    except (TypeError,ValueError): price_options=[]
    if not price_options:
        legacy_match=re.search(r'(\d[\d.,]*)\s*(USD|EUR|TRY|SAR|TL|\$|€)?',str(tour.get('price') or ''),re.I)
        if legacy_match:
            legacy_amount=legacy_match.group(1); legacy_currency=(legacy_match.group(2) or 'USD').upper()
            if ',' in legacy_amount and '.' in legacy_amount:
                legacy_amount=legacy_amount.replace('.','').replace(',','.') if legacy_amount.rfind(',')>legacy_amount.rfind('.') else legacy_amount.replace(',','')
            elif ',' in legacy_amount:
                legacy_amount=legacy_amount.replace(',','.') if re.search(r',\d{1,2}$',legacy_amount) else legacy_amount.replace(',','')
            elif legacy_amount.count('.')>1: legacy_amount=legacy_amount.replace('.','')
            legacy_currency={'TL':'TRY','$':'USD','€':'EUR'}.get(legacy_currency,legacy_currency)
            if legacy_currency not in ('USD','EUR','TRY','SAR'): legacy_currency='USD'
            price_options=[{'label':'Kişi başı fiyat','amount':legacy_amount,'currency':legacy_currency}]
    price_options=[option for option in price_options if isinstance(option,dict) and str(option.get('label','')).strip() and option.get('amount') not in ('',None) and option.get('currency') in ('USD','EUR','TRY','SAR')]
    structured=any(any(option.get(k) not in ('',None) for k in ('nights','days','room','category','event_name','event_outbound_date')) for option in price_options)
    if structured:
        variants=[]
        for option in price_options:
            nights=option.get('nights') or ''; days=option.get('days') or ''; duration=str(option.get('duration') or ' / '.join(x for x in ([f'{nights} gece' if nights else '',f'{days} gün' if days else '']) if x) or duration or ''); category=str(option.get('category') or ''); room=str(option.get('room') or '')
            key='|'.join((str(nights),str(days),duration))
            variants.append({'category':category,'room':room,'duration':duration,'duration_key':key,'event_name':str(option.get('event_name') or ''),'event_outbound_date':str(option.get('event_outbound_date') or ''),'event_return_date':str(option.get('event_return_date') or ''),'event_key':'|'.join((str(option.get('event_name') or ''),str(option.get('event_outbound_date') or ''))),'event_label':' · '.join(x for x in (str(option.get('event_name') or ''),str(option.get('event_outbound_date') or option.get('event_return_date') or '')) if x),'stays':[{'city':str(s.get('city') or '')[:80],'hotel':str(s.get('hotel') or '')[:120],'nights':s.get('nights')} for s in (option.get('stays') or []) if isinstance(s,dict) and s.get('city')][:20],'label':str(option.get('label') or ' · '.join(x for x in (category,duration,room) if x)),'amount':option['amount'],'currency':option['currency']})
        safe_variants=html.escape(json.dumps(variants,ensure_ascii=False),quote=True)
        categories=list(dict.fromkeys(v['category'] for v in variants)); durations=list({v['duration_key']:v for v in variants}.values()); rooms=list(dict.fromkeys(v['room'] for v in variants)); events=list({v['event_key']:v for v in variants if v['event_name'] or v['event_outbound_date']}.values())
        def variant_select(title,attribute,items,value,label):
            if len(items)<2:return ''
            return f'<label class="tour-variant-select"><span>{title}</span><select data-variant-{attribute}>'+''.join(f'<option value="{html.escape(str(value(item)),quote=True)}">{html.escape(str(label(item)))}</option>' for item in items)+'</select></label>'
        first=variants[0]
        selectors=variant_select('Etkinlik tarihi','event',events,lambda x:x['event_key'],lambda x:x['event_label'])+variant_select('Program','category',categories,lambda x:x,lambda x:x or 'Standart')+variant_select('Süre','duration',durations,lambda x:x['duration_key'],lambda x:x['duration'])+variant_select('Oda tipi','room',rooms,lambda x:x,lambda x:x or 'Standart')
        price_list_html=f'<div class="tour-variant-picker" data-tour-variants data-tour-price-box data-variants="{safe_variants}">{selectors}<div class="tour-variant-current"><span data-selected-variant>{html.escape(first["label"])}</span><b data-money-amount="{html.escape(str(first["amount"]))}" data-money-currency="{first["currency"]}">{html.escape(str(first["amount"]))} {first["currency"]}</b></div><div class="tour-variant-stays" data-variant-stays hidden></div><p class="tour-rate-status" data-rate-note>Güncel kur bilgisi alınıyor…</p></div>'
    elif price_options:
        price_rows=''.join(f'<div class="tour-price-option"><span>{html.escape(str(option["label"]))}<small>{option["currency"]}</small></span><b data-money-amount="{html.escape(str(option["amount"]))}" data-money-currency="{option["currency"]}">{html.escape(str(option["amount"]))} {option["currency"]}</b></div>' for option in price_options)
        price_list_html=f'<div class="tour-price-list" data-tour-price-box>{price_rows}</div><p class="tour-rate-status" data-rate-note>Güncel kur bilgisi alınıyor…</p>'
    else:
        price_list_html=f'<div class="tour-price-value"><span>Kişi başı fiyat</span><strong>{price}</strong></div>' if price else '<div class="tour-price-value"><span>Kişi başı fiyat</span><a href="iletisim.html">Güncel fiyat için bilgi alın ↗</a></div>'
    rate_control=''
    content_html=f'<section class="tour-itinerary"><p class="eyebrow">PROGRAM AKIŞI</p><h2>Tur programı</h2><div>{content}</div></section>' if content else '<section class="tour-itinerary"><p class="eyebrow">PROGRAM AKIŞI</p><h2>Program ayrıntıları</h2><div>Uçuş, tarih, konaklama ve oda-fiyat seçenekleri bu program için yukarıda yer alır. Gün gün gezi akışı ve müsaitliği ekibimizle teyit edin.</div></section>'
    detail_facts=[('Süre',duration),('Gidiş',outbound_date),('Dönüş',return_date),('Uçuş bilgisi',flight_info),('Konaklama',accommodation)]
    facts_html=''.join(f'<div class="tour-detail-fact"><span>{label}</span><b>{value}</b></div>' for label,value in detail_facts if value)
    extra_sections=''.join(f'<section class="tour-itinerary"><p class="eyebrow">{label}</p><h2>{heading}</h2><div>{value}</div></section>' for label,heading,value in [('FİYAT SEÇENEKLERİ','Oda ve fiyat seçenekleri',price_details),('FİYATA DAHİL','Dahil olan hizmetler',included_services),('FİYATA DAHİL DEĞİL','Dahil olmayan hizmetler',excluded_services)] if value)
    document=f'''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{description}"><title>{title} | Ecmel Turizm</title><link rel="stylesheet" href="../styles.css?v=premium-storefront-20261023b"><style>
    .tour-detail-page{{background:#f7f7f3;min-height:100vh;padding-bottom:84px}}.tour-detail-banner{{position:relative;min-height:300px;display:grid;align-items:end;overflow:hidden;background:#183027;color:#fff}}.tour-detail-banner>img,.tour-detail-banner>video{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.tour-detail-banner:after{{content:'';position:absolute;inset:0;background:linear-gradient(90deg,#142c24dc,#142c2470 62%,#142c2430),linear-gradient(0deg,#142c2488,transparent 60%)}}.tour-detail-banner-copy{{position:relative;z-index:1;padding:65px 0 43px}}.tour-detail-banner h1{{max-width:850px;margin:0;font:500 clamp(42px,7vw,76px)/.98 Georgia,serif;letter-spacing:-.035em}}.tour-detail-banner .eyebrow{{color:#dfc993}}.tour-detail-layout{{display:grid;grid-template-columns:minmax(300px,.82fr) minmax(0,1.18fr);gap:46px;margin-top:38px;align-items:start}}.tour-detail-media-column{{position:sticky;top:22px}}.tour-detail-media-frame{{position:relative;aspect-ratio:1/1;overflow:hidden;border-radius:8px;background:#e6e4da;box-shadow:0 18px 48px #20392e18}}.tour-detail-media-frame img,.tour-detail-media-frame video{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.tour-brochure-link{{display:flex;align-items:center;justify-content:space-between;margin-top:14px;padding:17px 18px;background:#20392e;color:#fff;font-size:13px;font-weight:700;border-radius:4px}}.tour-detail-info{{display:grid;gap:24px}}.tour-detail-main h2{{margin:0 0 20px;color:#20392e;font:500 30px Georgia,serif}}.tour-detail-description{{color:#5e6b62;font-size:15px;line-height:1.8;max-width:760px}}.tour-detail-facts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:28px 0 39px}}.tour-detail-fact{{padding:17px 18px;border:1px solid #e1e4dc;background:#fffefa}}.tour-detail-fact span{{display:block;margin-bottom:7px;color:#9a7a47;font-size:9px;font-weight:700;letter-spacing:.13em;text-transform:uppercase}}.tour-detail-fact b{{color:#36483d;font-size:13px;font-weight:600}}.tour-itinerary{{padding-top:25px;border-top:1px solid #dfe3dc}}.tour-itinerary+.tour-itinerary{{margin-top:25px}}.tour-itinerary .eyebrow{{margin-bottom:10px}}.tour-itinerary>div{{white-space:pre-wrap;color:#667168;font-size:13px;line-height:1.9}}.tour-price-card{{align-self:start;padding:26px;background:#fffefa;border:1px solid #e2e2d8;border-top:3px solid #c6a567;box-shadow:0 14px 35px #2233290b}}.tour-price-card .eyebrow{{margin-bottom:12px}}.tour-price-card h2{{font:500 28px Georgia,serif;color:#20392e;margin:0 0 8px}}.tour-price-card>p:not(.eyebrow){{color:#778178;font-size:11px;line-height:1.7}}.tour-price-value{{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:17px 0;border-top:1px solid #e8e7df;border-bottom:1px solid #e8e7df;color:#455449;font-size:11px}}.tour-price-value strong{{color:#aa8448;font:600 24px Georgia}}.tour-price-value>a{{color:#37604a;font-size:11px;font-weight:700}}.tour-price-value:has(>a){{display:grid;gap:7px}}.tour-currency-control{{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:16px;color:#647169;font-size:10px}}.tour-currency-control select{{width:auto;min-width:145px;margin:0;padding:9px 30px 9px 11px;border:1px solid #e0e5df;background:#fff;color:#304238;font-size:11px}}.tour-price-list{{margin-top:6px;border-top:1px solid #e8e7df}}.tour-price-option{{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:13px 0;border-bottom:1px solid #e8e7df;color:#455449;font-size:11px}}.tour-price-option>span{{display:grid;gap:4px}}.tour-price-option small{{color:#9a825b;font-size:9px;letter-spacing:.08em}}.tour-price-option b{{color:#20392e;font-size:14px;text-align:right;white-space:nowrap}}.tour-rate-status{{margin:9px 0 0!important;font-size:9px!important;color:#8a938b!important}}.tour-detail-actions{{display:grid;gap:9px;margin-top:17px}}.tour-detail-actions a,.tour-detail-actions button{{display:flex;min-height:46px;align-items:center;justify-content:center;padding:12px;border:0;background:#234b3b;color:#fff;font-size:11px;font-weight:700;cursor:pointer}}.tour-detail-actions button{{background:#ede9df;color:#3a4b40}}.tour-breadcrumb{{padding-top:24px;color:#89938b;font-size:10px}}.tour-breadcrumb a{{color:#536358}}.tour-detail-placeholder{{position:absolute;inset:0;background:radial-gradient(ellipse at 75% 22%,#a88a5555,transparent 38%),linear-gradient(115deg,#183027,#304b3c 62%,#87714b)}}.tour-detail-footer{{margin-top:55px;padding-top:20px;border-top:1px solid #dfe3dc;color:#8a938b;font-size:10px}}@media(max-width:760px){{.tour-detail-media-column{{position:static}}.tour-detail-media-frame{{max-width:460px;aspect-ratio:1/1;margin:0 auto}}.tour-detail-info{{gap:18px}}.tour-detail-banner{{min-height:250px}}.tour-detail-banner-copy{{padding:49px 0 31px}}.tour-detail-layout{{grid-template-columns:1fr;gap:23px;margin-top:30px}}.tour-detail-facts{{grid-template-columns:1fr 1fr;gap:8px;margin:20px 0 27px}}.tour-detail-fact{{padding:13px}}.tour-detail-fact b{{font-size:11px}}.tour-price-card{{padding:20px}}.tour-detail-main h2{{font-size:25px}}.tour-detail-description{{font-size:13px}}}}
    @media print{{.utility-bar,.header,.tour-detail-actions,.tour-breadcrumb,.tour-detail-footer{{display:none!important}}.tour-detail-page{{padding:0;background:#fff}}.tour-detail-banner{{min-height:180px;print-color-adjust:exact;-webkit-print-color-adjust:exact}}.tour-detail-layout{{grid-template-columns:.8fr 1.2fr;gap:22px;margin-top:24px}}.tour-detail-media-column{{position:static}}.tour-price-card{{box-shadow:none}}}}
    </style></head><body><div class="utility-bar"><div class="shell utility-inner"><span>2008’den beri seyahat deneyimi</span><div><a href="tel:+902126353552">0212 635 35 52</a><a href="mailto:info@ecmeltur.com">info@ecmeltur.com</a></div></div></div><header class="header"><div class="shell header-inner"><a class="brand" href="../index.html" aria-label="Ecmel Turizm ana sayfa"><img class="brand-logo" src="../assets/ecmel-logo.png" alt="Ecmel Turizm"></a><button class="menu-toggle" aria-label="Menüyü aç" aria-expanded="false" aria-controls="primary-nav"><span></span><span></span><span></span></button><nav class="nav" id="primary-nav" aria-label="Ana menü"></nav><a class="header-cta" href="iletisim.html">İletişim <span>↗</span></a></div></header><main class="tour-detail-page"><div class="shell tour-breadcrumb"><a href="../index.html">Ana Sayfa</a>　›　<a href="../pages/turlar.html">Turlar</a>　›　{category}　›　{title}</div><section class="tour-detail-banner"><div class="shell tour-detail-banner-copy"><p class="eyebrow">{category.upper()}</p><h1>{title}</h1></div></section><div class="shell tour-detail-layout"><aside class="tour-detail-media-column"><div class="tour-detail-media-frame">{media_html}</div>{brochure_html}</aside><div class="tour-detail-info"><div class="tour-detail-main"><p class="eyebrow">ECMEL TURİZM · {category.upper()}</p><h2>Yolculuk ayrıntıları</h2><p class="tour-detail-description">{description}</p><div class="tour-detail-facts"><div class="tour-detail-fact"><span>Tarih / dönem</span><b>{date}</b></div><div class="tour-detail-fact"><span>Program</span><b>{category}</b></div>{facts_html}</div>{content_html}{extra_sections}</div><aside class="tour-price-card"><p class="eyebrow">PROGRAM BİLGİSİ</p><h2>{title}</h2><p>Fiyatlar seçtiğiniz para biriminde güncel referans kurla gösterilir.</p>{rate_control}{price_list_html}<div class="tour-detail-actions"><a href="iletisim.html">Bilgi ve rezervasyon ↗</a><button type="button" onclick="window.print()">PDF olarak kaydet</button></div></aside></div></div><div class="shell tour-detail-footer">© 2026 Ecmel Turizm · A Grubu Seyahat Acentası · IATA</div></main><script src="../script.js?v=premium-navigation-20261023b"></script><script src="../cms-public.js?v=verified-tour-content-20261023ib"></script><script src="../booking.js?v=request-form-r7-variants-20261023"></script><script>
    (()=>{{const select=document.querySelector('[data-currency-select]');if(!select)return;const rows=[...document.querySelectorAll('[data-price-amount]')],status=document.querySelector('[data-rate-status]');let rates=null;const fmt=(n,c)=>new Intl.NumberFormat('tr-TR',{{style:'currency',currency:c,maximumFractionDigits:2}}).format(n);function paint(){{const target=select.value;rows.forEach(row=>{{const amount=Number(row.dataset.priceAmount),source=row.dataset.priceCurrency;let value=amount;if(rates&&source!=='USD')value/=rates[source];if(rates&&target!=='USD')value*=rates[target];row.textContent=fmt(value,rates?target:source)}});if(status)status.textContent=rates?'Referans kur tarihi: '+rates.date+' · Merkez bankası kaynaklı günlük kur':'Kur bilgisi alınamadı; fiyatlar kayıtlı para biriminde gösteriliyor.'}}select.addEventListener('change',paint);fetch('../api/public/rates',{{cache:'no-store'}}).then(r=>{{if(!r.ok)throw Error();return r.json()}}).then(data=>{{rates=Object.assign({{date:data.date,USD:1}},data.rates);paint()}}).catch(paint)}})();
    </script></body></html>'''
    return document

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT),**kw)
    def log_message(self,fmt,*args): print('[%s] %s'%(self.log_date_time_string(),fmt%args))
    def send_error(self,code,message=None,explain=None):
        if code not in (404,500): return super().send_error(code,message,explain)
        background=''
        try:
            db=connect(); row=db.execute("SELECT value FROM settings WHERE key='backgrounds_json'").fetchone(); db.close()
            backgrounds=json.loads(row['value']) if row and row['value'] else {}
            candidate=backgrounds.get('error_404','')
            if isinstance(candidate,str) and (candidate.startswith('/') or candidate.startswith('https://')): background=candidate.replace('\\','').replace('"','').replace("'",'')
        except Exception: pass
        if not background: background='/assets/mecca-hero.jpg'
        is_missing=code==404
        title='Bu sayfa bulunamadı' if is_missing else 'Bir sorun oluştu'
        description='Aradığınız sayfa taşınmış veya adresi değişmiş olabilir.' if is_missing else 'İsteğiniz şu anda tamamlanamadı. Lütfen biraz sonra yeniden deneyin.'
        style=f"background-image:linear-gradient(115deg,#142c24e8,#142c2477),url(&quot;{html.escape(background,quote=True)}&quot;);" if background else 'background:radial-gradient(ellipse at 78% 22%,#b18d5266,transparent 38%),linear-gradient(125deg,#142c24,#385341 65%,#9a8055);'
        body=f'<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{code} · Ecmel Turizm</title><body style="margin:0;min-height:100vh;background-color:#142c24;{style}background-size:cover;background-position:center;display:grid;place-items:center;color:#fff;font-family:Arial,sans-serif"><main style="max-width:680px;padding:52px 28px;text-align:center"><p style="letter-spacing:.22em;color:#dfc993;font-size:12px">ECMEL TURİZM · {code}</p><h1 style="font:500 clamp(40px,8vw,72px)/1.04 Georgia,serif;margin:18px 0">{title}</h1><p style="max-width:520px;margin:0 auto;color:#f1eee6;font-size:17px;line-height:1.7">{description}</p><a href="/" style="display:inline-block;margin-top:30px;padding:16px 24px;background:#f4f0e8;color:#244b3b;text-decoration:none;font-weight:700">Ana sayfaya dön　↗</a></main></body></html>'.encode('utf-8')
        self.send_response(code); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers()
        if getattr(self,'command','GET')!='HEAD':
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
    def send_json(self,obj,status=200):
        data=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def body_json(self):
        n=int(self.headers.get('Content-Length','0'))
        if n>2_000_000: raise ValueError('İstek boyutu çok büyük')
        return json.loads(self.rfile.read(n) or b'{}')
    def authorized_origin(self):
        origin=self.headers.get('Origin')
        return not origin or urlparse(origin).netloc==self.headers.get('Host')
    def admin_session(self,db):
        token=''
        for part in self.headers.get('Cookie','').split(';'):
            key,_,value=part.strip().partition('=')
            if key=='ecmel_admin': token=value
        if not token:return False
        digest=hashlib.sha256(token.encode()).hexdigest()
        now=int(time.time())
        row=db.execute('SELECT expires FROM sessions WHERE token_hash=?',(digest,)).fetchone()
        if not row or int(row['expires'])<=now:
            if row:db.execute('DELETE FROM sessions WHERE token_hash=?',(digest,)); db.commit()
            return False
        db.execute('UPDATE sessions SET expires=? WHERE token_hash=?',(now+ADMIN_IDLE_TIMEOUT_SECONDS,digest)); db.commit()
        self._admin_session_token=token
        return True
    def require_admin(self):
        db=connect(); ok=self.admin_session(db); db.close()
        if not ok:self.send_json({'error':'Yönetici oturumu gerekli.'},401)
        elif getattr(self,'_admin_session_token',''):self._refresh_admin_cookie=self._admin_session_token
        return ok
    def admin_cookie(self,token,max_age):
        self.send_header('Set-Cookie',f'ecmel_admin={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}')
    def admin_body(self):
        n=int(self.headers.get('Content-Length','0'))
        if n>12_000_000:raise ValueError('İstek boyutu çok büyük (12 MB sınırı).')
        data=json.loads(self.rfile.read(n) or b'{}')
        if not isinstance(data,dict):raise ValueError('İstek gövdesi nesne biçiminde olmalı.')
        return data
    def admin_settings(self,db):
        return {r['key']:r['value'] for r in db.execute('SELECT * FROM settings')}
    def send_public_html(self,document,status=200):
        db=connect(); row=db.execute("SELECT value FROM settings WHERE key='webmaster_verification'").fetchone(); db.close()
        raw=str(row['value']).strip() if row else ''
        match=re.search(r'<meta\b[^>]*name=["\']google-site-verification["\'][^>]*content=["\']([A-Za-z0-9_-]+)["\']',raw,re.I)
        token=match.group(1) if match else (raw if re.fullmatch(r'[A-Za-z0-9_-]+',raw) else '')
        if token:
            meta=f'<meta name="google-site-verification" content="{html.escape(token,quote=True)}">'
            document=re.sub(r'<meta\b(?=[^>]*name=["\']google-site-verification["\'])[^>]*>',meta,document,count=1,flags=re.I) if re.search(r'<meta\b(?=[^>]*name=["\']google-site-verification["\'])[^>]*>',document,re.I) else document.replace('</head>',meta+'</head>',1)
        body=document.encode('utf-8'); self.send_response(status); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-cache'); self.end_headers(); return self.wfile.write(body)
    def page_data(self,db):
        settings=self.admin_settings(db); settings.pop('password_hash',None)
        return {'pages':[dict(r) for r in db.execute('SELECT * FROM pages ORDER BY slug')],
          'tours':[dict(r) for r in db.execute('SELECT * FROM tours ORDER BY id DESC')],
          'settings':settings,
          'reviews':[dict(r) for r in db.execute('SELECT * FROM guest_reviews ORDER BY created_at DESC LIMIT 200')],
          'messages':[dict(r) for r in db.execute('SELECT * FROM contact_messages ORDER BY created_at DESC LIMIT 200')],
          'analytics':self.analytics_data(db)}
    def handle_admin_api(self,method,p):
        if p=='/api/admin/status' and method=='GET':
            db=connect(); row=db.execute("SELECT value FROM settings WHERE key='password_hash'").fetchone(); configured=bool(row and str(row['value']).startswith('pbkdf2$') and self.admin_settings(db).get('admin_username')); ok=self.admin_session(db); db.close()
            if ok and getattr(self,'_admin_session_token',''):self._refresh_admin_cookie=self._admin_session_token
            return self.send_json({'configured':configured,'authenticated':ok,'setup_key_required':bool(os.environ.get('ECMEL_ADMIN_SETUP_KEY'))})
        if p in ('/api/admin/setup','/api/admin/login') and method=='POST':
            if not self.authorized_origin():return self.send_json({'error':'İstek kaynağı doğrulanamadı.'},403)
            ip=self.client_address[0]; now=time.time(); recent=[t for t in _login_attempts.get(ip,[]) if now-t<900]; _login_attempts[ip]=recent
            if len(recent)>=12:return self.send_json({'error':'Çok fazla deneme yapıldı. 15 dakika sonra tekrar deneyin.'},429)
            _login_attempts[ip].append(now)
            try:data=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            username=str(data.get('username','')).strip()[:80]; password=str(data.get('password',''))
            if len(username)<3 or len(password)<12 or len(password)>256:return self.send_json({'error':'Kullanıcı adı en az 3, parola 12–256 karakter olmalı.'},400)
            db=connect(); row=db.execute("SELECT value FROM settings WHERE key='password_hash'").fetchone()
            if p.endswith('setup'):
                setup_key=os.environ.get('ECMEL_ADMIN_SETUP_KEY','')
                if setup_key and not secrets.compare_digest(str(data.get('setup_key','')),setup_key):db.close(); return self.send_json({'error':'Kurulum anahtarı geçersiz.'},403)
                if not setup_key and self.client_address[0] not in ('127.0.0.1','::1'):db.close(); return self.send_json({'error':'Uzak ilk kurulum için ECMEL_ADMIN_SETUP_KEY yapılandırılmalı.'},403)
                if row and str(row['value']).startswith('pbkdf2$') and self.admin_settings(db).get('admin_username'):db.close(); return self.send_json({'error':'İlk yönetici hesabı zaten oluşturulmuş.'},409)
                salt=secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,310000)
                db.execute("INSERT INTO settings(key,value) VALUES('password_hash',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('pbkdf2$310000$'+salt.hex()+'$'+digest.hex(),))
                db.execute("INSERT INTO settings(key,value) VALUES('admin_username',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(username,)); db.commit()
            else:
                valid=False
                if row and username==self.admin_settings(db).get('admin_username',''):
                    try:_,rounds,salt_hex,expected=row['value'].split('$'); actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt_hex),int(rounds)).hex(); valid=secrets.compare_digest(actual,expected)
                    except Exception:valid=False
                if not valid:db.close(); return self.send_json({'error':'Kullanıcı adı veya parola hatalı.'},401)
            token=secrets.token_urlsafe(36); db.execute('INSERT INTO sessions(token_hash,expires) VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),int(now+ADMIN_IDLE_TIMEOUT_SECONDS))); db.commit(); db.close()
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.admin_cookie(token,ADMIN_IDLE_TIMEOUT_SECONDS); self.end_headers(); self.wfile.write(b'{"ok":true}'); return
        if p=='/api/admin/logout' and method=='POST':
            if not self.authorized_origin():return self.send_json({'error':'İstek kaynağı doğrulanamadı.'},403)
            db=connect(); token=''
            for part in self.headers.get('Cookie','').split(';'):
                k,_,v=part.strip().partition('=')
                if k=='ecmel_admin':token=v
            if token:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)); db.commit()
            db.close(); self.send_response(200); self.send_header('Content-Type','application/json'); self.admin_cookie('',0); self.end_headers(); self.wfile.write(b'{"ok":true}'); return
        if not self.require_admin():return
        if method=='POST' and not self.authorized_origin():return self.send_json({'error':'İstek kaynağı doğrulanamadı.'},403)
        if p=='/api/admin/data' and method=='GET':
            db=connect(); data=self.page_data(db); db.close(); return self.send_json(data)
        # Backward-compatible endpoint used by an older admin tab that polls
        # the inbox directly. Keep it behind the same admin-session check.
        if p=='/api/admin/contact-messages' and method=='GET':
            db=connect(); rows=[dict(r) for r in db.execute('SELECT * FROM contact_messages ORDER BY created_at DESC LIMIT 200')]; db.close(); return self.send_json(rows)
        if p=='/api/admin/test-rates' and method=='GET':
            db=connect(); row=db.execute("SELECT value FROM settings WHERE key='integrations_json'").fetchone(); db.close(); config={}
            try:config=json.loads(row['value']) if row else {}
            except Exception:pass
            base=config.get('base_currency','USD'); provider=config.get('rate_provider','open-er-api')
            if provider=='frankfurter' and config.get('rate_endpoint','').startswith('https://api.frankfurter.dev/v2/rates?base=USD&quotes=EUR,TRY'): provider='open-er-api'
            endpoint=config.get('rate_endpoint') if provider=='custom' else (f'https://api.frankfurter.dev/v2/rates?base={base}&quotes=USD,EUR,TRY,SAR' if provider=='frankfurter' else f'https://open.er-api.com/v6/latest/{base}')
            if not isinstance(endpoint,str) or not endpoint.startswith('https://'):return self.send_json({'error':'API uç noktası HTTPS olmalı.'},400)
            headers={'User-Agent':'EcmelTurizm/1.0'}
            if config.get('rate_provider')=='custom' and config.get('rate_api_key'):headers['Authorization']='Bearer '+str(config['rate_api_key'])
            try:
                request=urllib.request.Request(endpoint,headers=headers)
                with urllib.request.urlopen(request,timeout=8) as response:rows=json.loads(response.read()); status=response.status
                if isinstance(rows,dict):
                    rates=rows.get('conversion_rates') or rows.get('rates') or {}
                    base=rows.get('base_code') or rows.get('base') or base
                    date=rows.get('time_last_update_utc') or rows.get('date','')
                else:
                    rates={r['quote']:r['rate'] for r in rows}; date=rows[0]['date'] if rows else ''
                if not isinstance(rates,dict) or not all(k in rates for k in ('USD','EUR','TRY','SAR')):return self.send_json({'error':'Kur servisi gerekli USD, EUR, TRY ve SAR kurlarını döndürmedi.'},502)
                return self.send_json({'ok':True,'status':status,'base':base,'date':date,'rates':rates})
            except Exception:return self.send_json({'error':'API bağlantısı başarısız oldu. Uç nokta ve anahtar bilgilerini kontrol edin.'},502)
        if p=='/api/admin/pages' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            slug=re.sub(r'[^a-z0-9-]','',str(d.get('slug','')).lower().replace('_','-'))[:100]
            title=str(d.get('title','')).strip()[:180]
            if not slug or not title:return self.send_json({'error':'Sayfa adresi ve başlık zorunludur.'},400)
            if slug in ('admin','api','assets','pages') or slug.startswith('dinamik-'):return self.send_json({'error':'Bu sayfa adresi kullanılamaz.'},400)
            db=connect()
            if d.get('create_only') and db.execute('SELECT 1 FROM pages WHERE slug=?',(slug,)).fetchone():db.close(); return self.send_json({'error':'Bu sayfa adresi zaten kullanılıyor.'},409)
            group=str(d.get('group_key') or page_group(slug)); group=group if group in ('tours','services','other') else 'other'
            db.execute('''INSERT INTO pages(slug,title,description,media,video,active,status,content,group_key) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET title=excluded.title,description=excluded.description,media=excluded.media,video=excluded.video,active=excluded.active,status=excluded.status,content=excluded.content,group_key=excluded.group_key''',(slug,title,str(d.get('description',''))[:1000],str(d.get('media',''))[:1000],str(d.get('video',''))[:1000],1 if d.get('active',True) else 0,str(d.get('status','published'))[:20],str(d.get('content',''))[:500000],group)); db.commit(); db.close(); return self.send_json({'ok':True,'slug':slug})
        if p=='/api/admin/pages/delete' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            slug=str(d.get('slug',''))
            if slug=='home':return self.send_json({'error':'Ana sayfa silinemez; içeriğini düzenleyebilirsiniz.'},400)
            db=connect()
            db.execute("UPDATE pages SET active=FALSE,status='deleted' WHERE slug=?",(slug,))
            db.execute("UPDATE tours SET active=FALSE,status='deleted' WHERE static_page_slug=?",(slug,))
            remove_from_menus(db,slug)
            db.commit(); db.close(); return self.send_json({'ok':True,'trashed':True})
        if p=='/api/admin/tours' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            title=str(d.get('title','')).strip()[:180]; slug=re.sub(r'[^a-z0-9-]','',str(d.get('slug','')).lower().replace('_','-'))[:100]
            if not title or not slug:return self.send_json({'error':'Tur adı ve adresi zorunludur.'},400)
            options=d.get('price_options',[])
            if not isinstance(options,list) or len(options)>200:return self.send_json({'error':'En fazla 200 oda fiyatı seçeneği ekleyebilirsiniz.'},400)
            for option in options:
                if not isinstance(option,dict) or not str(option.get('label','')).strip() or option.get('currency') not in ('USD','EUR','TRY','SAR'):
                    return self.send_json({'error':'Her fiyat seçeneğinde ad ve USD, EUR, TRY veya SAR para birimi bulunmalı.'},400)
                try:
                    amount=float(option.get('amount',0))
                    if amount<=0 or amount>100_000_000:raise ValueError()
                    option['amount']=amount; option['label']=str(option['label'])[:100]
                except Exception:return self.send_json({'error':'Fiyat tutarları sıfırdan büyük sayısal değerler olmalı.'},400)
                for field in ('nights','days'):
                    value=option.get(field)
                    if value not in ('',None):
                        try:
                            value=int(value)
                            if value<1 or value>180:raise ValueError()
                            option[field]=value
                        except Exception:return self.send_json({'error':'Gece ve gün sayıları 1 ile 180 arasında tam sayı olmalı.'},400)
                option['category']=str(option.get('category') or '')[:100]
                option['room']=str(option.get('room') or '')[:100]
                option['duration']=str(option.get('duration') or '')[:100]
                option['event_name']=str(option.get('event_name') or '')[:120]
                for field in ('event_outbound_date','event_return_date'):
                    value=str(option.get(field) or '')[:10]
                    if value:
                        try:datetime.strptime(value,'%Y-%m-%d')
                        except ValueError:return self.send_json({'error':'Etkinlik tarihlerini geçerli tarih biçiminde girin.'},400)
                    option[field]=value
                if option.get('event_outbound_date') and option.get('event_return_date') and option['event_return_date']<option['event_outbound_date']:
                    return self.send_json({'error':'Etkinlik dönüş tarihi gidiş tarihinden önce olamaz.'},400)
            db=None
            try:
                db=connect()
                if d.get('create_only') and db.execute('SELECT 1 FROM tours WHERE slug=?',(slug,)).fetchone():db.close(); return self.send_json({'error':'Bu tur adresi zaten kullanılıyor.'},409)
                db.execute('''INSERT INTO tours(slug,title,category,description,date,price,media,video,active,status,content,duration,outbound_date,return_date,flight_info,accommodation,price_details,included_services,excluded_services,price_options,brochure,record_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET title=excluded.title,category=excluded.category,description=excluded.description,date=excluded.date,price=excluded.price,media=excluded.media,video=excluded.video,active=excluded.active,status=excluded.status,content=excluded.content,duration=excluded.duration,outbound_date=excluded.outbound_date,return_date=excluded.return_date,flight_info=excluded.flight_info,accommodation=excluded.accommodation,price_details=excluded.price_details,included_services=excluded.included_services,excluded_services=excluded.excluded_services,price_options=excluded.price_options,brochure=excluded.brochure,record_type=excluded.record_type''',(slug,title,str(d.get('category','Yurtdışı Turlar'))[:100],str(d.get('description',''))[:1000],str(d.get('date',''))[:160],str(d.get('price',''))[:100],str(d.get('media',''))[:1000],str(d.get('video',''))[:1000],bool(d.get('active',True)),str(d.get('status','published'))[:20],str(d.get('content',''))[:500000],str(d.get('duration',''))[:100],str(d.get('outbound_date',''))[:50],str(d.get('return_date',''))[:50],str(d.get('flight_info',''))[:500],str(d.get('accommodation',''))[:500],str(d.get('price_details',''))[:2000],str(d.get('included_services',''))[:2000],str(d.get('excluded_services',''))[:2000],json.dumps(d.get('price_options',[]),ensure_ascii=False),str(d.get('brochure',''))[:1000],str(d.get('record_type','tour'))[:30])); db.commit(); db.close(); return self.send_json({'ok':True,'slug':slug})
            except Exception as error:
                self.log_error('Tur kaydı başarısız: %s',error)
                if db:
                    try:db.close()
                    except Exception:pass
                return self.send_json({'error':'Tur kaydı veritabanına yazılamadı. Bilgiler formda korunuyor; bağlantıyı kontrol edip yeniden deneyin.'},500)
        if p=='/api/admin/tours/delete' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            slug=str(d.get('slug','')); db=connect()
            row=db.execute('SELECT static_page_slug FROM tours WHERE slug=?',(slug,)).fetchone()
            db.execute("UPDATE tours SET active=FALSE,status='deleted' WHERE slug=?",(slug,))
            if row and row['static_page_slug']:
                db.execute("UPDATE pages SET active=FALSE,status='deleted' WHERE slug=?",(row['static_page_slug'],))
                remove_from_menus(db,row['static_page_slug'])
            db.commit(); db.close(); return self.send_json({'ok':True,'trashed':True})
        if p in ('/api/admin/trash/restore','/api/admin/trash/purge','/api/admin/trash/empty') and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            db=connect(); action=p.rsplit('/',1)[1]
            if action=='empty':
                items=[('page',r['slug']) for r in db.execute("SELECT slug FROM pages WHERE status='deleted'")]+[('tour',r['slug']) for r in db.execute("SELECT slug FROM tours WHERE status='deleted'")]
            else:
                items=[(str(d.get('kind','')),str(d.get('slug','')))]
            for kind,slug in items:
                if kind=='page':
                    if action=='restore':
                        db.execute("UPDATE pages SET active=TRUE,status='published' WHERE slug=? AND status='deleted'",(slug,))
                        db.execute("UPDATE tours SET active=TRUE,status='published' WHERE static_page_slug=? AND status='deleted'",(slug,))
                    else:
                        db.execute("DELETE FROM tours WHERE static_page_slug=? AND status='deleted'",(slug,))
                        db.execute("DELETE FROM pages WHERE slug=? AND status='deleted'",(slug,))
                        add_purged(db,[f'page:{slug}'])
                elif kind=='tour':
                    row=db.execute("SELECT static_page_slug FROM tours WHERE slug=? AND status='deleted'",(slug,)).fetchone()
                    if not row:continue
                    linked=row['static_page_slug']
                    if action=='restore':
                        db.execute("UPDATE tours SET active=TRUE,status='published' WHERE slug=?",(slug,))
                        if linked:db.execute("UPDATE pages SET active=TRUE,status='published' WHERE slug=? AND status='deleted'",(linked,))
                    else:
                        db.execute("DELETE FROM tours WHERE slug=? AND status='deleted'",(slug,))
                        if linked:
                            db.execute("DELETE FROM pages WHERE slug=? AND status='deleted'",(linked,))
                            add_purged(db,[f'page:{linked}'])
            db.commit(); db.close(); return self.send_json({'ok':True})
        if p=='/api/admin/settings' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            allowed={'menu_json','footer_menu_json','top_menu_json','site_name','logo','footer_logo','phone','email','address','whatsapp','instagram','facebook','footer_text','telegram','map_embed_url','google_analytics_id','webmaster_verification','recaptcha_site_key','recaptcha_enabled','maintenance_mode','maintenance_message','home_sections_json','home_sections_order_json','hero_images_json','backgrounds_json','about_image','translations_json','integrations_json','module_settings_json','site_language','supported_languages','seo_json'}
            db=connect()
            for key,value in d.items():
                if key not in allowed:continue
                raw=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
                if key=='supported_languages':
                    try:
                        languages=json.loads(raw) if isinstance(raw,str) else value
                        if not isinstance(languages,list) or not 1<=len(languages)<=20 or any(not isinstance(code,str) or not re.fullmatch(r'[a-z]{2,3}',code) for code in languages):db.close(); return self.send_json({'error':'Dil listesi geçersiz.'},400)
                        raw=json.dumps(list(dict.fromkeys(languages)),ensure_ascii=False)
                    except Exception:db.close(); return self.send_json({'error':'Dil listesi geçersiz.'},400)
                db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,raw[:8_000_000]))
            db.commit(); db.close()
            global _exchange_rates_cache
            if 'integrations_json' in d:_exchange_rates_cache=None
            return self.send_json({'ok':True})
        if p=='/api/admin/password' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            db=connect(); current=db.execute("SELECT value FROM settings WHERE key='password_hash'").fetchone(); valid=False
            try:_,rounds,salt_hex,expected=current['value'].split('$'); actual=hashlib.pbkdf2_hmac('sha256',str(d.get('current','')).encode(),bytes.fromhex(salt_hex),int(rounds)).hex(); valid=secrets.compare_digest(actual,expected)
            except Exception:valid=False
            password=str(d.get('password',''))
            if not valid:db.close(); return self.send_json({'error':'Mevcut parola hatalı.'},401)
            if len(password)<12 or len(password)>256:db.close(); return self.send_json({'error':'Yeni parola 12–256 karakter olmalı.'},400)
            salt=secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,310000).hex(); db.execute("UPDATE settings SET value=? WHERE key='password_hash'",('pbkdf2$310000$'+salt.hex()+'$'+digest,)); db.commit(); db.close(); return self.send_json({'ok':True})
        if p=='/api/admin/files' and method=='GET':
            items=[]
            for f in UPLOADS.iterdir():
                if f.is_file() and not f.name.startswith('.'):
                    st=f.stat(); items.append({'name':f.name,'url':'/assets/uploads/'+f.name,'size':st.st_size,'modified':int(st.st_mtime)})
            items.sort(key=lambda x:x['modified'],reverse=True); return self.send_json(items)
        if p=='/api/admin/files/delete' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            name=str(d.get('name',''))
            if not re.fullmatch(r'[A-Za-z0-9._-]{1,120}',name) or name.startswith('.'):return self.send_json({'error':'Geçersiz dosya adı.'},400)
            target=UPLOADS/name
            if not target.is_file():return self.send_json({'error':'Dosya bulunamadı.'},404)
            target.unlink(); return self.send_json({'ok':True})
        if p=='/api/admin/upload' and method=='POST':
            try:d=self.admin_body(); data_url=str(d.get('data',''))
            except Exception as e:return self.send_json({'error':str(e)},400)
            match=re.fullmatch(r'data:(image/(?:jpeg|png|webp|gif)|application/pdf);base64,([A-Za-z0-9+/=]+)',data_url)
            if not match:return self.send_json({'error':'JPG, PNG, WebP, GIF veya PDF dosyası yükleyebilirsiniz.'},400)
            try:blob=base64.b64decode(match.group(2),validate=True)
            except Exception:return self.send_json({'error':'Dosya okunamadı.'},400)
            if not blob or len(blob)>8_000_000:return self.send_json({'error':'Dosya en fazla 8 MB olmalı.'},400)
            if match.group(1)=='application/pdf' and not blob.startswith(b'%PDF-'):return self.send_json({'error':'Seçilen dosya geçerli bir PDF değil.'},400)
            ext={'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/gif':'gif','application/pdf':'pdf'}[match.group(1)]
            name=secrets.token_hex(16)+'.'+ext; (UPLOADS/name).write_bytes(blob); return self.send_json({'ok':True,'url':'/assets/uploads/'+name})
        if p=='/api/admin/ai/brochure' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            match=re.fullmatch(r'data:(image/(?:jpeg|png|webp|gif)|application/pdf);base64,([A-Za-z0-9+/=]+)',str(d.get('data','')))
            if not match:return self.send_json({'error':'Broşür PDF, JPG, PNG veya WebP olmalı.'},400)
            try:
                result=ai_read_brochure(match.group(1),match.group(2))
            except AiError as e:return self.send_json({'error':str(e)},e.status)
            return self.send_json({'ok':True,'tour':result})
        if p=='/api/admin/review' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            db=connect(); db.execute('UPDATE guest_reviews SET status=? WHERE id=?',(str(d.get('status','pending'))[:20],int(d.get('id',0)))); db.commit(); db.close(); return self.send_json({'ok':True})
        if p=='/api/admin/message' and method=='POST':
            try:d=self.admin_body()
            except Exception as e:return self.send_json({'error':str(e)},400)
            db=connect(); db.execute('UPDATE contact_messages SET status=? WHERE id=?',(str(d.get('status','read'))[:20],int(d.get('id',0)))); db.commit(); db.close(); return self.send_json({'ok':True})
        return self.send_json({'error':'Bulunamadı'},404)
    def analytics_data(self,db):
        now=datetime.now().astimezone(); today=now.date(); yesterday=today-timedelta(days=1); month_start=today.replace(day=1)
        prev_month_end=month_start-timedelta(days=1); prev_month_start=prev_month_end.replace(day=1)
        epoch=lambda d:int(datetime.combine(d,datetime_time.min,tzinfo=now.tzinfo).timestamp())
        host=configured_analytics_host(db)
        if not host:
            start=today-timedelta(days=29)
            return {'mode':'preview','active':0,'today':{'views':0,'visitors':0,'change':0},'yesterday':{'views':0,'visitors':0},'month':{'views':0,'visitors':0,'change':0},'series':[{'date':(start+timedelta(days=i)).isoformat(),'views':0} for i in range(30)]}
        rows=db.execute('SELECT visitor_hash,visited_at FROM analytics_visits WHERE source_host=? AND visited_at>=?',(host,epoch(prev_month_start))).fetchall()
        counts={}; unique_today=set(); unique_yesterday=set(); unique_month=set(); unique_prev_month=set(); today_views=yesterday_views=month_views=prev_month_views=0
        for row in rows:
            day=datetime.fromtimestamp(row['visited_at'],now.tzinfo).date(); vh=row['visitor_hash']
            counts[day.isoformat()]=counts.get(day.isoformat(),0)+1
            if day==today: today_views+=1; unique_today.add(vh)
            if day==yesterday: yesterday_views+=1; unique_yesterday.add(vh)
            if day>=month_start: month_views+=1; unique_month.add(vh)
            if prev_month_start<=day<=prev_month_end: prev_month_views+=1; unique_prev_month.add(vh)
        start=today-timedelta(days=29); series=[{'date':(start+timedelta(days=i)).isoformat(),'views':counts.get((start+timedelta(days=i)).isoformat(),0)} for i in range(30)]
        active=db.execute('SELECT COUNT(*) AS count FROM analytics_active WHERE source_host=? AND last_seen>=?',(host,int(time.time())-300)).fetchone()['count']
        def change(current,previous): return round((current-previous)*100/previous) if previous else (100 if current else 0)
        return {'mode':'live','active':active,'today':{'views':today_views,'visitors':len(unique_today),'change':change(today_views,yesterday_views)},'yesterday':{'views':yesterday_views,'visitors':len(unique_yesterday)},'month':{'views':month_views,'visitors':len(unique_month),'change':change(month_views,prev_month_views)},'series':series}
    def do_GET(self):
        try:return self._serve_GET()
        except Exception:return self.send_error(500)
    def do_HEAD(self):
        try:return super().do_HEAD()
        except Exception:return self.send_error(500)
    def _serve_GET(self):
        p=urlparse(self.path).path
        if p.startswith('/api/admin/'):
            return self.handle_admin_api('GET',p)
        if p in ('/admin','/admin/','/admin/index.html'):
            self.path='/admin/index.html'
            return super().do_GET()
        if p.startswith('/api/') and not p.startswith('/api/public/') and p!='/api/analytics/visit':
            return self.send_json({'error':'Bulunamadı'},404)
        db=connect(); maintenance=self.admin_settings(db).get('maintenance_mode')=='true'; maintenance_message=self.admin_settings(db).get('maintenance_message','Web sitemiz kısa süre içinde yeniden hizmetinizde olacak.'); db.close()
        if maintenance and not (p=='/admin' or p.startswith('/admin/') or p.startswith('/api/admin/')):
            if p.startswith('/api/'):return self.send_json({'error':'Site bakım modunda.'},503)
            body=f'<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Bakım çalışması · Ecmel Turizm</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f3ee;color:#20392e;font-family:Arial,sans-serif;text-align:center"><main style="max-width:560px;padding:48px;background:#fff;border:1px solid #e2e4dc"><p style="color:#a58650;letter-spacing:.16em;font-size:11px">ECMEL TURİZM</p><h1 style="font:500 38px Georgia;margin:16px 0">Kısa bir bakım arasındayız.</h1><p style="color:#69756e;line-height:1.7">{html.escape(maintenance_message)}</p><a style="color:#244b3b;font-weight:700" href="tel:+902126353552">0212 635 35 52</a></main></body></html>'.encode(); self.send_response(503); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Retry-After','3600'); self.send_header('Content-Length',str(len(body))); self.end_headers(); return self.wfile.write(body)
        if p in ('/robots.txt','/sitemap.xml'):
            db=connect(); rows={r['key']:r['value'] for r in db.execute("SELECT key,value FROM settings WHERE key IN ('seo_json','site_url')")}; raw_pages=[dict(r) for r in db.execute("SELECT slug FROM pages WHERE active=TRUE AND status='published'")]; raw_tours=[dict(r) for r in db.execute("SELECT slug,static_page_slug FROM tours WHERE active=TRUE AND status='published'")]; db.close()
            try: seo=json.loads(rows.get('seo_json','{}'))
            except Exception: seo={}
            configured=str(seo.get('site_url') or rows.get('site_url') or '').strip().rstrip('/'); parsed=urlparse(configured)
            origin=f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme in ('http','https') and parsed.netloc else f"{'https' if self.headers.get('X-Forwarded-Proto')=='https' else 'http'}://{self.headers.get('Host','127.0.0.1')}"
            if p=='/robots.txt':
                body=f'User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n'.encode(); self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','public, max-age=3600'); self.end_headers(); return self.wfile.write(body)
            localized=seo.get('pages',{}).get('tr',{}); urls=[]; today=datetime.utcnow().date().isoformat()
            for row in raw_pages:
                slug=row['slug']; path='/' if slug=='home' else f'/pages/{slug}.html'; override=localized.get(slug,{}).get('canonical',''); candidate=urlparse(override) if override else None
                loc=override if candidate and candidate.scheme in ('http','https') and candidate.netloc else origin+path
                urls.append(f'<url><loc>{html.escape(loc)}</loc><lastmod>{today}</lastmod></url>')
            for tour in raw_tours:
                urls.append(f'<url><loc>{html.escape(origin+"/pages/dinamik-"+tour["slug"]+".html")}</loc><lastmod>{today}</lastmod></url>')
            body=('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(urls)+'</urlset>').encode(); self.send_response(200); self.send_header('Content-Type','application/xml; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','public, max-age=3600'); self.end_headers(); return self.wfile.write(body)
        if p=='/api/public/content':
            hidden=','.join("'"+slug+"'" for slug in TOUR_PAGE_SLUGS)
            db=connect(); pages=[dict(r) for r in db.execute(f"SELECT * FROM pages WHERE active=TRUE AND status='published' AND slug NOT IN ({hidden})")]; tours=[dict(r) for r in db.execute("SELECT * FROM tours WHERE active=TRUE AND status='published' ORDER BY id DESC")]; settings={r['key']:r['value'] for r in db.execute("SELECT * FROM settings WHERE key NOT IN ('password_hash','admin_username','integrations_json') AND key NOT LIKE 'draft:%'")}; db.close()
            try:
                translations=json.loads(settings.get('translations_json','{}')); page_slugs={x['slug'] for x in pages}|{x['slug'] for x in tours if x.get('static_page_slug')}; tour_slugs={x['slug'] for x in tours}
                for lang in translations.values():
                    lang['pages']={k:v for k,v in lang.get('pages',{}).items() if k in page_slugs}
                    lang['tours']={k:v for k,v in lang.get('tours',{}).items() if k in tour_slugs}
                settings['translations_json']=json.dumps(translations,ensure_ascii=False)
            except Exception:settings.pop('translations_json',None)
            return self.send_json({'pages':pages,'tours':tours,'settings':settings})
        if p=='/api/public/rates':
            global _exchange_rates_cache
            force=urlparse(self.path).query=='force=1'
            db=connect(); row=db.execute("SELECT value FROM settings WHERE key='integrations_json'").fetchone(); db.close(); integration={}
            try: integration=json.loads(row['value']) if row else {}
            except Exception: pass
            try: cache_hours=max(1,min(72,int(integration.get('rate_cache_hours',12))))
            except Exception: cache_hours=12
            if not force and _exchange_rates_cache and time.time()-_exchange_rates_cache['updated']<cache_hours*3600:return self.send_json(_exchange_rates_cache['data'])
            try:
                base=integration.get('base_currency','USD'); provider=integration.get('rate_provider','open-er-api')
                if provider=='frankfurter' and integration.get('rate_endpoint','').startswith('https://api.frankfurter.dev/v2/rates?base=USD&quotes=EUR,TRY'): provider='open-er-api'
                endpoint=integration.get('rate_endpoint') if provider=='custom' else (f'https://api.frankfurter.dev/v2/rates?base={base}&quotes=USD,EUR,TRY,SAR' if provider=='frankfurter' else f'https://open.er-api.com/v6/latest/{base}')
                if not isinstance(endpoint,str) or not endpoint.startswith('https://'):raise ValueError('Kur API adresi HTTPS olmalı.')
                headers={'User-Agent':'EcmelTurizm/1.0'}
                if integration.get('rate_provider')=='custom' and integration.get('rate_api_key'):headers['Authorization']='Bearer '+str(integration['rate_api_key'])
                request=urllib.request.Request(endpoint,headers=headers)
                with urllib.request.urlopen(request,timeout=5) as response: rows=json.loads(response.read())
                if isinstance(rows,dict):
                    raw_rates=rows.get('conversion_rates') or rows.get('rates') or {}; rate_base=rows.get('base_code') or rows.get('base') or base; rate_date=rows.get('time_last_update_utc') or rows.get('date',datetime.utcnow().date().isoformat())
                else: raw_rates={row['quote']:row['rate'] for row in rows}; rate_base=base; rate_date=rows[0]['date'] if rows else datetime.utcnow().date().isoformat()
                raw_rates[rate_base]=1
                if not all(currency in raw_rates for currency in ('USD','EUR','TRY','SAR')):raise ValueError('Kur servisi gerekli dövizleri döndürmedi.')
                data={'date':rate_date,'base':rate_base,'rates':{currency:raw_rates[currency] for currency in ('USD','EUR','TRY','SAR')}}
                _exchange_rates_cache={'data':data,'updated':time.time()}; return self.send_json(data)
            except Exception:return self.send_json({'error':'Güncel referans kuru şu anda alınamıyor.'},503)
        if p=='/api/public/reviews':
            db=connect(); rows=[dict(r) for r in db.execute("SELECT name,trip,review,created_at FROM guest_reviews WHERE status='approved' ORDER BY created_at DESC LIMIT 12")]; db.close(); return self.send_json(rows)
        if p.startswith('/pages/dinamik-') and p.endswith('.html'):
            slug=p[len('/pages/dinamik-'):-5]; db=connect(); row=db.execute("SELECT * FROM tours WHERE slug=? AND active=TRUE AND status='published'",(slug,)).fetchone(); db.close()
            if not row:return self.send_error(404)
            document=tour_detail_document(dict(row))
            return self.send_public_html(document)
        if p.startswith('/pages/') and p.endswith('.html'):
            slug=Path(unquote(p)).stem
            _db=connect(); _gone=f'page:{slug}' in purged_keys(_db); _db.close()
            if _gone:return self.send_error(404,'Bu sayfa silindi.')
            if slug in TOUR_PAGES and slug not in ('umre','hac'):
                db=connect(); tour=db.execute("SELECT * FROM tours WHERE static_page_slug=? AND active=TRUE AND status='published'",(slug,)).fetchone(); db.close()
                if tour:
                    return self.send_public_html(tour_detail_document(dict(tour)))
            db=connect(); tour_row=db.execute('SELECT active,status FROM tours WHERE static_page_slug=?',(slug,)).fetchone() if slug in TOUR_PAGE_SLUGS else None
            # A dormant static tour record must not shadow its published category page
            # (notably the Umre page, whose static tour entry may be kept as a draft).
            page_row=db.execute('SELECT active,status FROM pages WHERE slug=?',(slug,)).fetchone()
            row=page_row or tour_row
            custom=db.execute('SELECT * FROM pages WHERE slug=?',(slug,)).fetchone()
            db.close()
            if row and (not row['active'] or row['status']!='published'): return self.send_error(404,'Bu sayfa şu anda yayında değil.')
            if not (ROOT/'pages'/f'{slug}.html').exists() and custom and custom['active'] and custom['status']=='published':
                return self.send_public_html(custom_page_document(dict(custom)))
        if p in ('/','/index.html'):
            db=connect(); row=db.execute("SELECT active,status FROM pages WHERE slug='home'").fetchone(); db.close()
            if row and (not row['active'] or row['status']!='published'): return self.send_error(404,'Ana sayfa şu anda yayında değil.')
        if p.endswith('.html') or p in ('/','/index.html'):
            target=Path(self.translate_path(self.path))
            if target.is_dir():target=target/'index.html'
            if target.is_file():
                try:return self.send_public_html(target.read_text(encoding='utf-8'))
                except (OSError,UnicodeError):pass
        return super().do_GET()
    def do_POST(self):
        p=urlparse(self.path).path
        if p.startswith('/api/admin/'):return self.handle_admin_api('POST',p)
        if p in ('/api/public/contact','/api/public/reviews'):
            if not self.authorized_origin():return self.send_json({'error':'İstek kaynağı doğrulanamadı.'},403)
            try:data=self.body_json()
            except Exception as e:return self.send_json({'error':str(e)},400)
            if str(data.get('website','')).strip():return self.send_json({'ok':True,'message':'Talebiniz alındı.'},201)
            if p.endswith('contact'):
                db=connect(); row=db.execute("SELECT value FROM settings WHERE key='integrations_json'").fetchone(); db.close()
                try: captcha=json.loads(row['value']) if row else {}
                except Exception: captcha={}
                secret=str(captcha.get('recaptcha_secret_key','')).strip()
                if secret:
                    token=str(data.get('g-recaptcha-response') or data.get('recaptcha_token') or '').strip()
                    if not token:return self.send_json({'error':'Lütfen reCAPTCHA doğrulamasını tamamlayın.'},400)
                    try:
                        payload=urlencode({'secret':secret,'response':token}).encode()
                        request=urllib.request.Request('https://www.google.com/recaptcha/api/siteverify',data=payload,headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
                        with urllib.request.urlopen(request,timeout=8) as response: verified=json.loads(response.read())
                    except Exception:return self.send_json({'error':'Güvenlik doğrulaması şu anda yapılamıyor. Lütfen tekrar deneyin.'},503)
                    if not verified.get('success'):return self.send_json({'error':'reCAPTCHA doğrulanamadı. Lütfen yeniden deneyin.'},400)
            name=str(data.get('name','')).strip()[:100]; field='message' if p.endswith('contact') else 'review'; message=str(data.get(field,'')).strip()[:3000]
            if len(name)<2 or len(message)<10:return self.send_json({'error':'Ad soyad ve en az 10 karakterlik bir metin gerekli.'},400)
            db=connect(); now=int(time.time())
            if p.endswith('contact'):
                email=str(data.get('email','')).strip()[:200]; phone=str(data.get('phone','')).strip()[:40]; subject=str(data.get('subject','')).strip()[:160]
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):db.close(); return self.send_json({'error':'Geçerli bir e-posta adresi girin.'},400)
                db.execute('INSERT INTO contact_messages(name,email,phone,subject,message,created_at) VALUES(?,?,?,?,?,?)',(name,email,phone,subject,message,now)); db.commit(); db.close(); return self.send_json({'ok':True,'message':'Mesajınız ekibimize iletildi.'},201)
            trip=str(data.get('trip','')).strip()[:100]; db.execute("INSERT INTO guest_reviews(name,trip,review,status,created_at) VALUES(?,?,?,'pending',?)",(name,trip,message,now)); db.commit(); db.close(); return self.send_json({'ok':True,'message':'Yorumunuz inceleme için alındı.'},201)
        if p=='/api/analytics/visit':
            if not self.authorized_origin():return self.send_json({'error':'İstek kaynağı doğrulanamadı.'},403)
            try:data=self.body_json()
            except Exception as e:return self.send_json({'error':str(e)},400)
            visitor=data.get('visitor_id',''); page=data.get('page','/')
            if not isinstance(visitor,str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,80}',visitor):return self.send_json({'error':'Ziyaret anahtarı geçersiz.'},400)
            page=page if isinstance(page,str) and page.startswith('/') else '/'; page=page.split('?',1)[0][:180]
            db=connect(); source_host=analytics_host(self.headers.get('Host','')); configured_host=configured_analytics_host(db)
            if not configured_host or source_host!=configured_host:
                db.close(); return self.send_json({'ok':True,'counted':False,'reason':'preview_or_unconfigured_domain'})
            now=int(time.time()); visitor_hash=hashlib.sha256(visitor.encode()).hexdigest()
            db.execute('INSERT INTO analytics_visits(visitor_hash,page,visited_at,source_host) VALUES(?,?,?,?)',(visitor_hash,page,now,source_host))
            db.execute('INSERT INTO analytics_active(visitor_hash,last_seen,source_host) VALUES(?,?,?) ON CONFLICT(visitor_hash) DO UPDATE SET last_seen=excluded.last_seen,source_host=excluded.source_host',(visitor_hash,now,source_host))
            global _analytics_last_prune
            if now-_analytics_last_prune>21600:
                db.execute('DELETE FROM analytics_visits WHERE visited_at<?',(now-90*86400,)); db.execute('DELETE FROM analytics_active WHERE last_seen<?',(now-600,)); _analytics_last_prune=now
            db.commit(); db.close(); return self.send_json({'ok':True})
        return self.send_json({'error':'Bulunamadı'},404)
    def end_headers(self):
        if getattr(self,'_refresh_admin_cookie',''):
            self.admin_cookie(self._refresh_admin_cookie,ADMIN_IDLE_TIMEOUT_SECONDS)
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','strict-origin-when-cross-origin'); self.send_header('X-Frame-Options','DENY')
        super().end_headers()
    def do_DELETE(self):
        p=urlparse(self.path).path
        if p.startswith('/api/admin/'):return self.handle_admin_api('DELETE',p)
        return self.send_json({'error':'Bulunamadı'},404)

if __name__=='__main__':
    db=connect(); seed_pages(db); seed_tours_from_pages(db); seed_admin_defaults(db); db.close()
    host=os.environ.get('ECMEL_HOST','127.0.0.1'); port=int(os.environ.get('PORT','4173'))
    print(f'Ecmel Turizm site server: http://{host}:{port}/')
    ThreadingHTTPServer((host,port),Handler).serve_forever()
