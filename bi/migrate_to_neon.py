#!/usr/bin/env python3
"""One-time copy of local CMS records into the Neon database in DATABASE_URL."""
import os, sqlite3
from site_server import DB as SQLITE_DB, connect, seed_admin_defaults

if not os.environ.get('DATABASE_URL'):
    raise SystemExit('DATABASE_URL eksik. Proje kökündeki .env dosyasına Neon bağlantı dizesini ekleyin.')
if not SQLITE_DB.exists():
    raise SystemExit('Yerel CMS veritabanı bulunamadı: '+str(SQLITE_DB))

source=sqlite3.connect(SQLITE_DB); source.row_factory=sqlite3.Row
remote=connect()
try:
    candidates={
        'pages':['slug','title','description','media','video','active','status','content'],
        'tours':['id','slug','title','category','description','date','price','media','video','active','status','content','static_page_slug','record_type','duration','outbound_date','return_date','flight_info','accommodation','price_details','included_services','excluded_services','price_options'],
        'settings':['key','value'],
    }
    for table,possible in candidates.items():
        available={r['name'] for r in source.execute('PRAGMA table_info('+table+')')}
        columns=[name for name in possible if name in available]
        rows=source.execute('SELECT '+','.join(columns)+' FROM '+table).fetchall()
        key='slug' if table=='pages' else 'key' if table=='settings' else 'slug'
        for row in rows:
            vals=tuple(row[c] for c in columns)
            updates=','.join(f'{c}=EXCLUDED.{c}' for c in columns if c!=key)
            sql=f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['?']*len(columns))}) ON CONFLICT ({key}) DO UPDATE SET {updates}"
            remote.execute(sql,vals)
        print(f'{table}: {len(rows)} kayıt aktarıldı')
    seed_admin_defaults(remote)
    remote.execute("SELECT setval(pg_get_serial_sequence('tours','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM tours")
    remote.commit()
except Exception:
    remote.connection.rollback()
    raise
finally:
    remote.close(); source.close()
print('Aktarım tamamlandı. Medya dosyaları Neon’a aktarılmaz; assets/uploads klasöründe kalır.')
