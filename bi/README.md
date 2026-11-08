# Ecmel Turizm sitesi ve yönetim paneli

Yerel önizleme ve yönetim için proje klasöründe:

```sh
python3 site_server.py
```

Site `http://127.0.0.1:4173/`, yönetim paneli `http://127.0.0.1:4173/admin/` adresinde açılır. İlk panel açılışında en az 12 karakterli yönetici parolasıyla hesap oluşturun. Sunucu varsayılan olarak yalnızca yerel bilgisayar bağlantısını (`127.0.0.1`) dinler. Uzak sunucuda ilk hesabı kuracaksanız `.env` içinde `ECMEL_ADMIN_SETUP_KEY` için uzun ve rastgele bir değer tanımlayın; anahtarı kurulum ekranında girin.

## Panelde yönetilebilenler

- Sayfalar: içerik, başlık, açıklama, URL, görünürlük, yayın durumu ve kapak görseli. Yeni sayfalar kendi adresleriyle yayınlanır.
- Menüler: ana gezinme, üst bant ve footer bağlantıları; öğe ekleme, kaldırma, sıralama ve alt menü ilişkisi.
- Turlar: kategori, tarih, süre, rota, konaklama, medya, program ve çoklu para biriminde fiyat seçenekleri.
- Marka/görünüm: header ve footer logoları, ana sayfa slaytları, bölüm görselleri ve ana sayfa bölümlerinin görünürlüğü/sırası.
- Diller: Türkçe, İngilizce, Arapça ve eklenebilir diğer diller için sayfa, tur, menü ve marka çevirileri.
- Mesajlar, misafir yorumları, iletişim bilgileri, kur API bağlantısı, site modülleri, bakım ekranı ve yönetici parolası.

Yüklenen JPG, PNG, WebP ve GIF dosyaları `assets/uploads/` altında saklanır. İçerik kayıtları `data/` veritabanında tutulur. Veritabanı veya mevcut içerik kayıtları silinmez.

Neon/PostgreSQL kullanımı için `.env.example` dosyasındaki `DATABASE_URL` ayarını kendi ortamınızda yapılandırın. Gizli API anahtarlarını site içerik API’sinde yayınlamayın; entegrasyon ayarları yalnızca oturum açmış panel API’siyle sunulur.
