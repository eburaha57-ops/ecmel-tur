from html import escape
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote

ROOT = Path(__file__).parent
PAGES = ROOT / "pages"

def page(slug, title, section, description, children=(), highlights=(), parent=None):
    return {
        "slug": slug,
        "title": title,
        "section": section,
        "description": description,
        "children": list(children),
        "highlights": list(highlights),
        "parent": parent,
    }


PAGES_DATA = [
    page("turlar", "Turlarımız", "TURLAR", "Hac, umre, kültür ve yurt içi programlarımızı inceleyin.", ["umre", "hac", "kultur-turlari", "yurtdisi-turlar", "yurtici-turlar"]),
    page("umre", "Umre Programları", "UMRE", "Umre yolculuğunuz için program, konaklama ve ulaşım tercihlerinizi ekibimizle birlikte planlayın. Güncel tarih ve fiyat bilgisi için bize ulaşın.", highlights=["Program ve dönem seçenekleri", "Konaklama ve ulaşım tercihleri", "Kişi sayınıza göre güncel fiyat teklifi"], parent="turlar"),
    page("hac", "Hac Programları", "HAC", "Hac yolculuğuna dair başvuru, konaklama ve ulaşım seçeneklerini ekibimizle görüşün. Güncel dönem ve resmi süreç bilgileri için bize ulaşın.", highlights=["Başvuru ve dönem bilgisi", "Konaklama ve ulaşım seçenekleri", "Güncel program ve ücret bilgisi"], parent="turlar"),
    page("kultur-turlari", "Kültür Turları", "KÜLTÜR TURLARI", "Özbekistan ve Endülüs rotalarındaki kültür turlarımızı inceleyin.", ["ozbekistan-turu", "endulus-turu"], parent="turlar"),
    page("ozbekistan-turu", "Özbekistan Turu", "KÜLTÜR TURLARI", "Semerkant, Buhara ve Hiva’nın İpek Yolu mirasını keşfedin. Tarih, uçuş, konaklama ve güncel fiyat seçenekleri için ekibimizle görüşün.", highlights=["Semerkant, Buhara ve Hiva rotası", "Uçuş ve konaklama seçenekleri", "Güncel tarih ve fiyat teklifi"], parent="kultur-turlari"),
    page("endulus-turu", "Endülüs Turu", "KÜLTÜR TURLARI", "Sevilla, Córdoba ve Granada’nın tarihî mirasını bir araya getiren Endülüs rotasını keşfedin. Program ve güncel fiyat bilgisi için bize ulaşın.", highlights=["Sevilla, Córdoba ve Granada rotası", "Ulaşım ve konaklama seçenekleri", "Güncel tarih ve fiyat teklifi"], parent="kultur-turlari"),
    page("yurtdisi-turlar", "Yurtdışı Turlar", "YURTDIŞI TURLAR", "Dubai ve Fas rotalarındaki yurtdışı turlarımızı keşfedin.", ["misir-turu", "dubai-turu", "balkan-turu", "fas-turu", "bosna-turu"], parent="turlar"),
    page("misir-turu", "Mısır Turu", "YURTDIŞI TURLAR", "Gize piramitleri ve Mısır’ın tarihî mirası çevresinde planlanan rotayı keşfedin. Güncel tarih, ulaşım ve fiyat seçenekleri için ekibimizle görüşün.", highlights=["Gize ve tarihî rota seçenekleri", "Uçuş ve konaklama bilgisi", "Güncel program ve fiyat teklifi"], parent="yurtdisi-turlar"),
    page("dubai-turu", "Dubai Turu", "YURTDIŞI TURLAR", "Dubai’nin simge yapıları ve şehir yaşamını keşfetmeye yönelik program seçenekleri için ekibimizle görüşün. Güncel tarih ve fiyat bilgisini paylaşalım.", highlights=["Şehir içi rota seçenekleri", "Uçuş ve konaklama bilgisi", "Güncel tarih ve fiyat teklifi"], parent="yurtdisi-turlar"),
    page("balkan-turu", "Balkan Turu", "YURTDIŞI TURLAR", "Mostar ve Balkan şehirlerinin tarihî dokusunu keşfedin. Rota, ulaşım, konaklama ve güncel program bilgileri için bize ulaşın.", highlights=["Şehir ve ziyaret noktası seçenekleri", "Ulaşım ve konaklama bilgisi", "Güncel tarih ve fiyat teklifi"], parent="yurtdisi-turlar"),
    page("fas-turu", "Fas Turu", "YURTDIŞI TURLAR", "Marakeş’in renkli meydanlarından Fas’ın tarihî şehirlerine uzanan bir rota keşfedin. Güncel program ve fiyat seçenekleri için ekibimizle görüşün.", highlights=["Marakeş ve şehir rotası seçenekleri", "Ulaşım ve konaklama bilgisi", "Güncel tarih ve fiyat teklifi"], parent="yurtdisi-turlar"),
    page("bosna-turu", "Bosna Turu", "YURTDIŞI TURLAR", "Saraybosna ve Bosna Hersek’in tarihî duraklarını keşfedin. Rota, konaklama ve güncel fiyat bilgileri için ekibimizle görüşün.", highlights=["Saraybosna ve tarihî duraklar", "Ulaşım ve konaklama bilgisi", "Güncel tarih ve fiyat teklifi"], parent="yurtdisi-turlar"),
    page("yurtici-turlar", "Yurtiçi Turlar", "YURTİÇİ TURLAR", "Günübirlik, konaklamalı ve kaplıca programlarımızı inceleyin.", ["gunubirlik-turlar", "konaklamali-turlar", "kaplica-turlari"], parent="turlar"),
    page("gunubirlik-turlar", "Günübirlik Turlar", "YURTİÇİ TURLAR · GÜNÜBİRLİK", "Edirne gezisi ve Çubuk Gölü’nden Mudurnu’ya günübirlik programlarımız.", ["edirne-gezisi", "cubuk-golunden-mudurnuya"], parent="yurtici-turlar"),
    page("edirne-gezisi", "Edirne Gezisi", "GÜNÜBİRLİK TUR", "Selimiye Camii, tarihî çarşılar, Sarayiçi ve Karaağaç’ı bir araya getiren kültür rotasını keşfedin. Hareket noktası, tarih ve güncel fiyat için ekibimizle görüşün.", highlights=["Selimiye, Eski ve Üç Şerefeli camileri", "Ali Paşa Çarşısı ve Sarayiçi", "Karaağaç ve tarihî gar"], parent="gunubirlik-turlar"),
    page("cubuk-golunden-mudurnuya", "Çubuk Gölü’nden Mudurnu’ya", "GÜNÜBİRLİK TUR", "Göynük’ün tarihî dokusunu, Çubuk Gölü’nün doğasını ve Mudurnu’nun geleneksel mimarisini buluşturan günübirlik rotayı keşfedin. Tarih ve güncel fiyat için ekibimize ulaşın.", highlights=["Göynük’te tarihî merkez ve Akşemseddin Türbesi", "Çubuk Gölü ve yel değirmenleri", "Mudurnu’nun geleneksel mimarisi"], parent="gunubirlik-turlar"),
    page("konaklamali-turlar", "Konaklamalı Turlar", "YURTİÇİ TURLAR · KONAKLAMALI", "Assos ve Kapadokya konaklamalı tur programlarımız.", ["assos-turu", "kapadokya-turu"], parent="yurtici-turlar"),
    page("assos-turu", "Assos Turu", "KONAKLAMALI TUR", "Ege kıyısındaki Assos Antik Kenti ve Behramkale çevresini keşfedin. Tur süresi, konaklama, dahil hizmetler ve güncel kişi başı fiyat için ekibimizle görüşün.", highlights=["Assos Antik Kenti ve Behramkale", "Konaklama ve ulaşım seçenekleri", "Güncel tarih ve fiyat teklifi"], parent="konaklamali-turlar"),
    page("kapadokya-turu", "Kapadokya Turu", "KONAKLAMALI TUR", "Kapadokya’nın vadilerini, kaya oluşumlarını ve tarihî yerleşimlerini keşfedin. Rota, konaklama ve isteğe bağlı aktiviteler hakkında güncel bilgi için bize ulaşın.", highlights=["Göreme ve çevresindeki doğal ve tarihî alanlar", "Konaklama ve ulaşım seçenekleri", "Güncel tarih ve fiyat teklifi"], parent="konaklamali-turlar"),
    page("kaplica-turlari", "Kaplıca Turları", "YURTİÇİ TURLAR · KAPLICA", "Balıkesir Sındırgı’daki Obam Termal konaklama ve tur bilgileri.", ["obam-termal"], parent="yurtici-turlar"),
    page("obam-termal", "Obam Termal · Sındırgı", "KAPLICA TURU", "Balıkesir’in Sındırgı ilçesindeki Obam Termal için konaklama ve ulaşım seçeneklerini öğrenin. Oda, termal alan, yemek ve güncel fiyat bilgisi için ekibimizle görüşün.", highlights=["Balıkesir · Sındırgı", "Oda, yemek ve termal alan seçenekleri", "Tarih ve kişi sayısına göre fiyat teklifi"], parent="kaplica-turlari"),
    page("hizmetler", "Diğer Seyahat Hizmetleri", "HİZMETLERİMİZ", "Vize, uçak bileti ve otel hizmetlerimiz için ilgili başlığı seçin.", ["vize", "ucak-bileti", "otel"]),
    page("vize", "Vize Danışmanlığı", "DİĞER HİZMETLER", "Vize başvuru sürecinde gerekli evraklar ve izlenecek adımlar hakkında ekibimizden destek alın.", highlights=["Başvuru süreci hakkında yönlendirme", "Güncel evrak listesi", "Seyahate göre danışmanlık"], parent="hizmetler"),
    page("ucak-bileti", "Uçak Bileti", "DİĞER HİZMETLER", "Seyahatinize uygun uçuş seçenekleri ve bilet işlemleri için bize ulaşın.", highlights=["Güzergâh ve uçuş seçenekleri", "Rezervasyon desteği", "Bireysel ve grup talepleri"], parent="hizmetler"),
    page("otel", "Otel ve Konaklama", "DİĞER HİZMETLER", "Seyahat planınıza uygun otel ve konaklama seçenekleri hakkında bilgi alın.", highlights=["Destinasyona uygun seçenekler", "Konaklama süresi ve oda tercihleri", "Rezervasyon desteği"], parent="hizmetler"),
    page("hakkimizda", "Hakkımızda", "KURUMSAL", "Ecmel Turizm 2008 yılında Fatih’te kuruldu. Hac ve umre alanındaki tecrübemizle misafirlerimize hizmet veriyoruz.", ["ekibimiz", "belgelerimiz", "misafir-yorumlari"], parent="kurumsal"),
    page("ekibimiz", "Ekibimiz", "KURUMSAL", "Seyahat öncesi hazırlıklardan yolculuk boyunca desteğe kadar ekibimizle doğrudan iletişim kurun.", highlights=["Program danışmanlığı", "Seyahat öncesi bilgilendirme", "Telefon ve e-posta üzerinden destek"], parent="hakkimizda"),
    page("belgelerimiz", "Belgelerimiz", "KURUMSAL", "Ecmel Turizm’in A Grubu seyahat acentası, IATA ve marka tescil belgeleri.", highlights=["A Grubu acenta belgesi", "IATA belgesi", "Marka tescil belgesi"], parent="hakkimizda"),
    page("misafir-yorumlari", "Misafir Yorumları", "KURUMSAL", "Ecmel Turizm ile seyahat eden misafirlerimizin onaylı deneyimlerini okuyun; kendi yorumunuzu ekibimizle paylaşın.", highlights=["Yayın öncesi incelenen misafir yorumları", "Yorumunuzu doğrudan paylaşma olanağı"], parent="hakkimizda"),
    page("banka-hesaplari", "Banka Hesapları", "KURUMSAL", "Ödeme öncesinde hesap sahibi ve IBAN bilgilerini ekibimizden teyit edin. Güvenliğiniz için teyit edilmemiş hesap bilgisi paylaşılmamaktadır.", highlights=["Hesap sahibi: Ecmel Turizm", "Güncel IBAN bilgisi için lütfen ofisimizle iletişime geçin", "Ödeme yapmadan önce hesap bilgilerini telefonla teyit edin"], parent="kurumsal"),
    page("referanslar", "Referanslar", "KURUMSAL", "Kurumsal iş birlikleri ve referans bilgileri için Ecmel Turizm ekibiyle iletişime geçin.", highlights=["Kurumsal iş birlikleri", "Referans talepleri", "Doğrudan iletişim"], parent="hakkimizda"),
    page("cerez-politikasi", "Çerez ve Ziyaret İstatistikleri", "GİZLİLİK VE VERİ KULLANIMI", "Sitede kullanılan zorunlu depolama alanları ve isteğe bağlı ziyaret istatistikleri hakkında bilgi alın.", highlights=["Zorunlu tercih kaydı tarayıcınızda saklanır", "Ziyaret istatistiği yalnızca açık onayınızdan sonra gönderilir", "Tercihinizi sayfanın altındaki bağlantıdan değiştirebilirsiniz"]),
    page("sss", "Sık Sorulan Sorular", "YARDIM MERKEZİ", "Hac, umre ve tur hazırlıklarıyla ilgili sık sorulan soruların yanıtları.", highlights=["Kayıt ve başvuru", "Pasaport ve gerekli belgeler", "Yolculuk öncesi hazırlık"], parent="yardim-merkezi"),
    page("seyahat-rehberi", "Seyahat Rehberi", "YARDIM MERKEZİ", "Hac ve umre hazırlığı, belgeler ve yolculuk öncesi bilgilere buradan ulaşın.", highlights=["Umre ve hac hazırlığı", "Seyahat belgeleri", "Blog ve duyurular"], parent="yardim-merkezi"),
    page("blog", "Blog ve Seyahat Notları", "BLOG", "Hac, umre, kültür rotaları ve seyahat hazırlıklarıyla ilgili yazılarımızı keşfedin.", ["seyahat-rehberi", "kultur-turlari", "galeri"], parent="yardim-merkezi"),
    page("galeri", "Fotoğraf ve Video Galerisi", "YARDIM MERKEZİ", "Türkiye’den ve dünyadan seçili destinasyon fotoğraflarıyla seyahat rotalarımıza göz atın.", highlights=["Destinasyon fotoğrafları", "Kültür ve seyahat rotaları"], parent="yardim-merkezi"),
    page("iletisim", "İletişim", "BİZE ULAŞIN", "Programlar ve seyahat hizmetleri hakkında ekibimizle görüşün.", highlights=["Telefon: 0212 635 35 52", "E-posta: info@ecmeltur.com", "Başakşehir / İstanbul"], parent=None),
]

BY_SLUG = {item["slug"]: item for item in PAGES_DATA}

# Wikimedia Commons originals are served through its width-limited redirect.
# Each page has a destination- or subject-specific image and a visible source link.
PHOTOS = {
    "turlar": ("Great Pyramid of Giza panorama.jpg", "Mısır’daki Gize piramitleri", "Wikimedia Commons · CC BY-SA 3.0"),
    "umre": ("mecca-hero.jpg", "Mekke’de Mescid-i Haram", "Ecmel Turizm arşivi"),
    "hac": ("mecca-hero.jpg", "Mekke’de Mescid-i Haram", "Ecmel Turizm arşivi"),
    "kultur-turlari": ("Registan 01.jpg", "Semerkant Registan Meydanı", "Wikimedia Commons"),
    "ozbekistan-turu": ("Registan 01.jpg", "Semerkant Registan Meydanı, Özbekistan", "Wikimedia Commons"),
    "endulus-turu": ("Alhambra Granada panorama.jpg", "Granada’daki Elhamra Sarayı", "Wikimedia Commons · CC BY-SA 4.0"),
    "yurtdisi-turlar": ("Great Pyramid of Giza panorama.jpg", "Gize Piramitleri, Mısır", "Wikimedia Commons · CC BY-SA 3.0"),
    "misir-turu": ("Great Pyramid of Giza panorama.jpg", "Gize Piramitleri, Mısır", "Wikimedia Commons · CC BY-SA 3.0"),
    "dubai-turu": ("Burj Khalifa (5697094559).jpg", "Burj Khalifa, Dubai", "Wikimedia Commons · CC BY 2.0"),
    "balkan-turu": ("Mostar - Stari Most (49033180333).jpg", "Mostar Köprüsü, Bosna Hersek", "Wikimedia Commons · CC BY 2.0"),
    "fas-turu": ("Marrakech Jemaa el-Fna (54246889027).jpg", "Jemaa el-Fnaa Meydanı, Marakeş", "Wikimedia Commons"),
    "bosna-turu": ("Sarajevo Old Town.JPG", "Saraybosna tarihî merkezi", "Wikimedia Commons · CC0"),
    "yurtici-turlar": ("Cappadocia Aerial View Landscape.jpg", "Kapadokya vadileri", "Wikimedia Commons · CC BY-SA 4.0"),
    "gunubirlik-turlar": ("Çubuk Gölü Panorama ve Ahşap İskele, Göynük, Bolu 2014.jpg", "Çubuk Gölü ve ahşap iskele, Göynük", "Wikimedia Commons"),
    "edirne-gezisi": ("Edirne Selimiye mosque in 2017 3282.jpg", "Selimiye Camii, Edirne", "Wikimedia Commons"),
    "cubuk-golunden-mudurnuya": ("Çubuk Gölü Panorama ve Ahşap İskele, Göynük, Bolu 2014.jpg", "Çubuk Gölü, Göynük", "Wikimedia Commons"),
    "konaklamali-turlar": ("A landscape view of Cappadocia.jpg", "Kapadokya’da gün doğumunda kaya oluşumları", "Wikimedia Commons · CC BY-SA 4.0"),
    "assos-turu": ("Assos Antik Kenti, Temple of Athena.jpg", "Assos Athena Tapınağı ve Ege kıyısı", "Wikimedia Commons"),
    "kapadokya-turu": ("Cappadocia Aerial View Landscape.jpg", "Kapadokya’nın havadan görünümü", "Wikimedia Commons · CC BY-SA 4.0"),
    "kaplica-turlari": ("Hotel room.jpg", "Termal tatil için konforlu konaklama", "Wikimedia Commons · CC BY 2.0"),
    "obam-termal": ("Hotel room.jpg", "Obam Termal için konaklama seçenekleri", "Wikimedia Commons · CC BY 2.0"),
    "hizmetler": ("Hotel room.jpg", "Konforlu otel odası", "Wikimedia Commons · CC BY 2.0"),
    "vize": ("US passport high resolution.jpg", "Pasaport ve seyahat belgeleri", "Wikimedia Commons · Public domain"),
    "ucak-bileti": ("Airbus A320 G-EUYW of British Airways London Heathrow.jpg", "Heathrow’dan havalanan Airbus A320 yolcu uçağı", "Wikimedia Commons"),
    "otel": ("Hotel room.jpg", "Aydınlık ve konforlu otel odası", "Wikimedia Commons · CC BY 2.0"),
    "hakkimizda": ("Bosphorus Istanbul 2007.jpg", "İstanbul Boğazı ve şehir silüeti", "Wikimedia Commons"),
    "ekibimiz": ("Tour guide points out Red Spouter to the group (49266435916).jpg", "Rehber eşliğinde doğa gezisine katılan ziyaretçiler", "Yellowstone National Park · Public domain"),
    "belgelerimiz": ("US passport high resolution.jpg", "Pasaport ve seyahat belgeleri", "Wikimedia Commons · Public domain"),
    "misafir-yorumlari": ("Tour guide points out Red Spouter to the group (49266435916).jpg", "Rehber eşliğinde geziye katılan ziyaretçiler", "Yellowstone National Park · Public domain"),
    "banka-hesaplari": ("Bosphorus Istanbul 2007.jpg", "İstanbul Boğazı", "Wikimedia Commons"),
    "referanslar": ("Bosphorus Istanbul 2007.jpg", "İstanbul Boğazı", "Wikimedia Commons"),
    "cerez-politikasi": ("US passport high resolution.jpg", "Seyahat belgeleri", "Wikimedia Commons · Public domain"),
    "sss": ("mecca-hero.jpg", "Mescid-i Haram ve Kâbe", "Ecmel Turizm arşivi"),
    "seyahat-rehberi": ("US passport high resolution.jpg", "Seyahat hazırlığında kullanılan pasaport", "Wikimedia Commons · Public domain"),
    "blog": ("Registan 01.jpg", "Semerkant Registan Meydanı", "Wikimedia Commons"),
    "galeri": ("Registan 01.jpg", "Semerkant Registan Meydanı", "Wikimedia Commons"),
    "iletisim": ("Bosphorus Istanbul 2007.jpg", "İstanbul Boğazı", "Wikimedia Commons"),
}

def photo_source(slug):
    filename, alt, credit = PHOTOS[slug]
    if filename == "mecca-hero.jpg":
        src = "../assets/mecca-hero.jpg"
    else:
        stem = unicodedata.normalize("NFKD", Path(filename).stem).encode("ascii", "ignore").decode("ascii").lower()
        local_name = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") + ".jpg"
        src = "../assets/destinations/" + local_name
    return src, alt, credit, ""

def href(slug):
    return f"/pages/{slug}.html"

def nav_group(label, links, class_name=""):
    body = "".join(f'<a href="{href(slug)}">{escape(text)}</a>' for text, slug in links)
    return f'<div class="nav-group"><button class="nav-trigger" aria-expanded="false">{escape(label)} <span>⌄</span></button><div class="nav-dropdown {class_name}">{body}</div></div>'

def nav_parent_group(label, slug, links, class_name=""):
    body = "".join(f'<a href="{href(link_slug)}">{escape(text)}</a>' for text, link_slug in links)
    return f'<div class="nav-group nav-parent-group"><div class="nav-parent-head"><a class="nav-link nav-parent-link" href="{href(slug)}">{escape(label)}</a><button class="nav-trigger" aria-label="{escape(label)} alt menüsünü aç" aria-expanded="false"><span>⌄</span></button></div><div class="nav-dropdown {class_name}">{body}</div></div>'

def make_nav():
    culture = [("Özbekistan Turu", "ozbekistan-turu"), ("Endülüs Turu", "endulus-turu"), ("Mısır Turu", "misir-turu"), ("Balkan Turu", "balkan-turu"), ("Bosna Turu", "bosna-turu")]
    abroad = [("Yurtdışı Turlar", "yurtdisi-turlar"), ("Dubai Turu", "dubai-turu"), ("Fas Turu", "fas-turu")]
    domestic = [("Günübirlik", "gunubirlik-turlar"), ("Konaklamalı", "konaklamali-turlar"), ("Kaplıca", "kaplica-turlari")]
    services = [("Vize", "vize"), ("Uçak bileti", "ucak-bileti"), ("Otel ve konaklama", "otel")]
    corporate = [("Hakkımızda", "hakkimizda"), ("Ekibimiz", "ekibimiz"), ("Belgelerimiz", "belgelerimiz"), ("Misafir yorumları", "misafir-yorumlari"), ("Banka Hesapları", "banka-hesaplari"), ("Referanslar", "referanslar")]
    help_links = [("Sık sorulan sorular", "sss"), ("Seyahat rehberi", "seyahat-rehberi"), ("Fotoğraf ve video galerisi", "galeri")]
    tour_columns = '<div class="nav-mega-column"><b>KÜLTÜR TURLARI</b>' + ''.join(f'<a href="{url}">{escape(t)}</a>' for t,url in culture) + '</div><div class="nav-mega-column"><b>YURTDIŞI TURLAR</b>' + ''.join(f'<a href="{href(s)}">{escape(t)}</a>' for t,s in abroad) + '</div>'
    domestic_columns = ''.join(f'<a href="{href(slug)}">{escape(label)}</a>' for label,slug in domestic)
    return ''.join([
        '<a class="nav-link" href="/pages/umre.html">Umre</a><a class="nav-link" href="/pages/hac.html">Hac</a>',
        nav_parent_group("Kültür Turları", "kultur-turlari", culture),
        nav_parent_group("Yurtdışı Turlar", "yurtdisi-turlar", abroad[1:]),
        nav_parent_group("Yurtiçi Turlar", "yurtici-turlar", domestic),
        nav_parent_group("Diğer Hizmetler", "hizmetler", services), nav_parent_group("Kurumsal", "hakkimizda", corporate),
        '<a class="nav-link" href="/pages/sss.html">SSS</a><a class="nav-link" href="/pages/blog.html">Blog</a>',
        '<a class="nav-link nav-contact-mobile" href="/pages/iletisim.html">İletişim</a>',
    ])

def related_links(item):
    result = []
    for index, slug in enumerate(item["children"], start=1):
        child = BY_SLUG[slug]
        target = f'#{"ozbekistan" if slug == "ozbekistan-turu" else "endulus"}' if item["slug"] == "kultur-turlari" else href(slug)
        result.append(f'<a class="page-link-card" href="{target}"><span class="page-card-number">0{index}</span><span class="page-card-section">{escape(child["section"])}</span><h3>{escape(child["title"])}</h3><p>{escape(child["description"])}</p><span class="page-card-cta">Detayları inceleyin <b>↗</b></span></a>')
    return ''.join(result)

def page_html(item):
    title = escape(item["title"])
    section = escape(item["section"])
    description = escape(item["description"])
    parent = BY_SLUG.get(item["parent"])
    crumbs = '<a href="/index.html">Ana Sayfa</a>'
    if parent:
        crumbs += f'<span>/</span><a href="{href(parent["slug"])}">{escape(parent["title"])}</a>'
    crumbs += f'<span>/</span><b>{title}</b>'
    highlights = ''.join(f'<li>{escape(text)}</li>' for text in item["highlights"])
    highlights_html = f'<ul class="page-highlights">{highlights}</ul>' if highlights else ''
    contact_form = '''<section class="contact-page-grid"><div class="contact-page-info"><p class="eyebrow">ECMEL TURİZM · İSTANBUL</p><h2>Size yardımcı olalım.</h2><p>Tur programları, kayıt ve seyahat hazırlıklarıyla ilgili sorularınızı ekibimize iletin.</p><a href="tel:+902126353552">0212 635 35 52</a><a href="mailto:info@ecmeltur.com">info@ecmeltur.com</a><address>Kayabaşı Mah. Adnan Menderes Bulvarı<br>Kuzey Yakası Ofisleri, A1 Blok K:2 D:17<br>Başakşehir / İstanbul</address></div><form class="contact-form contact-page-form" data-endpoint="/api/public/contact"><p class="eyebrow">MESAJINIZI İLETİN</p><h3>İletişim formu</h3><div class="form-row"><label>Ad soyad<input name="name" autocomplete="name" required minlength="2"></label><label>E-posta<input name="email" type="email" autocomplete="email" required></label></div><div class="form-row"><label>Telefon <small>(isteğe bağlı)</small><input name="phone" type="tel" autocomplete="tel"></label><label>Konu<input name="subject" maxlength="160"></label></div><label>Mesajınız<textarea name="message" rows="5" required minlength="10"></textarea></label><label class="form-trap" aria-hidden="true">Web sitesi<input name="website" tabindex="-1" autocomplete="off"></label><button class="button button-green" type="submit">Mesajı gönder <span>↗</span></button><p class="form-note" role="status">Bilgileriniz yalnızca talebinize yanıt vermek için kullanılır.</p></form></section>''' if item['slug']=='iletisim' else ''
    review_content = '''<section class="guest-review-page"><div class="guest-review-intro"><p class="eyebrow">YOLCULUK SONRASI</p><h2>Deneyiminizi paylaşın.</h2><p>Yorumlar yayınlanmadan önce ekibimiz tarafından incelenir.</p></div><div class="review-list" data-review-list aria-live="polite"></div><form class="contact-form guest-review-form" data-endpoint="/api/public/reviews"><h3>Misafir yorumu ekle</h3><div class="form-row"><label>Ad soyad<input name="name" autocomplete="name" required minlength="2"></label><label>Katıldığınız program <small>(isteğe bağlı)</small><input name="trip" maxlength="100" placeholder="Örn. Umre"></label></div><label>Yorumunuz<textarea name="review" rows="5" required minlength="10" maxlength="3000"></textarea></label><label class="form-trap" aria-hidden="true">Web sitesi<input name="website" tabindex="-1" autocomplete="off"></label><button class="button button-green" type="submit">Yorumu gönder <span>↗</span></button><p class="form-note" role="status">Paylaştığınız yorum onaydan sonra görüntülenir.</p></form></section>''' if item['slug']=='misafir-yorumlari' else ''
    section_title = "Çerez depolama alanları" if item["slug"] == "cerez-politikasi" else ("İki kültür, iki rota" if item["slug"] == "kultur-turlari" else ("İlgili başlıklar" if item["children"] else ("Turun öne çıkanları" if item["section"].endswith("TUR") else "Hizmet ayrıntıları")))
    src, photo_alt, photo_credit, photo_page = photo_source(item["slug"])
    photo_banner = f'<figure class="page-banner-photo"><img src="{escape(src, quote=True)}" alt="{escape(photo_alt, quote=True)}" fetchpriority="high"></figure><div class="page-banner-shade"></div>'
    culture_uz = photo_source("ozbekistan-turu")
    culture_es = photo_source("endulus-turu")
    culture_details = f'''<div class="culture-tour-grid">
<article class="culture-tour-panel" id="ozbekistan"><figure class="culture-tour-photo"><img src="{escape(culture_uz[0], quote=True)}" alt="Semerkant Registan Meydanı, Özbekistan" loading="lazy"></figure><p class="eyebrow">ORTA ASYA · TARİH VE MİMARİ</p><h3>Özbekistan Turu</h3><p>Semerkant, Buhara ve Hiva gibi İpek Yolu şehirlerinin tarihî dokusunu, mimarisini ve yerel kültürünü keşfetmeye yönelik rota.</p><div class="culture-tour-cities"><span>Semerkant</span><span>Buhara</span><span>Hiva</span></div><p class="culture-tour-note">Tarih, şehir sıralaması, uçuş, konaklama ve fiyat seçeneklerini ekibimizden öğrenin.</p><a href="/pages/iletisim.html">Özbekistan turu hakkında bilgi alın <b>↗</b></a></article>
<article class="culture-tour-panel" id="endulus"><figure class="culture-tour-photo"><img src="{escape(culture_es[0], quote=True)}" alt="Granada’daki Elhamra Sarayı" loading="lazy"></figure><p class="eyebrow">İSPANYA · ENDÜLÜS MİRASI</p><h3>Endülüs Turu</h3><p>Sevilla, Córdoba ve Granada’nın tarihî mirasını, mimarisini ve kültürel izlerini bir araya getiren keşif rotası.</p><div class="culture-tour-cities"><span>Sevilla</span><span>Córdoba</span><span>Granada</span></div><p class="culture-tour-note">Tarih, şehir sıralaması, uçuş, konaklama ve fiyat seçeneklerini ekibimizden öğrenin.</p><a href="/pages/iletisim.html">Endülüs turu hakkında bilgi alın <b>↗</b></a></article>
</div>''' if item["slug"] == "kultur-turlari" else ''
    cookie_details = '''<div class="cookie-policy-details"><h3>Zorunlu tercih kaydı</h3><p><code>ecmel_cookie_consent</code> tercihinizi tarayıcınızın yerel depolama alanında 180 gün saklar. Bu kayıt bir çerez değildir; analitik izni hatırlamak için gereklidir.</p><h3>İsteğe bağlı ziyaret istatistiği</h3><p>Yalnızca “Kabul et” seçeneğinden sonra <code>ecmel_visitor_id</code> adlı rastgele tanımlayıcı oluşturulur ve ziyaret edilen sayfanın yolu Ecmel Turizm sunucusuna gönderilir. Sunucuda bu tanımlayıcının özeti kullanılır; ziyaret kayıtları en fazla 90 gün, aktiflik kaydı 10 dakika tutulur. Reddetmeniz istatistik gönderimini durdurur.</p><h3>Üçüncü taraf çerezleri</h3><p>Bu sitede reklam ve sosyal ağ izleme çerezleri etkinleştirilmemiştir. Dil seçiminiz ve çerez tercihiniz tarayıcınızda saklanır. Tercihinizi istediğiniz zaman sayfa altındaki “Çerez tercihleri” bağlantısından değiştirebilirsiniz.</p><p>Veri işleme hakkında soru ve talepleriniz için <a href="mailto:info@ecmeltur.com">info@ecmeltur.com</a> adresinden bize ulaşın.</p></div>''' if item["slug"] == "cerez-politikasi" else ''
    rendered = f'''<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#f7f7f3"><meta name="description" content="{description}"><title>{title} | Ecmel Turizm</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"><link rel="stylesheet" href="/styles.css"></head>
<body><div class="utility-bar"><div class="shell utility-inner"><span>2008’den beri seyahat deneyimi</span><div><a href="tel:+902126353552">0212 635 35 52</a><a href="mailto:info@ecmeltur.com">info@ecmeltur.com</a><a class="utility-cta" href="https://wa.me/902126353552">WhatsApp <span>↗</span></a></div></div></div>
<header class="header"><div class="shell header-inner"><a class="brand" href="/index.html" aria-label="Ecmel Turizm ana sayfa"><span class="brand-name">ECMEL<span>TURİZM</span></span></a><button class="menu-toggle" aria-label="Menüyü aç" aria-expanded="false" aria-controls="primary-nav"><span></span><span></span><span></span></button><nav class="nav" id="primary-nav" aria-label="Ana menü"></nav><a class="header-cta" href="/pages/iletisim.html">İletişim <span>↗</span></a></div></header>
<main class="detail-page"><div class="shell breadcrumb">{crumbs}</div><section class="page-banner">{photo_banner}<div class="shell page-banner-inner"><div class="page-banner-copy"><p class="eyebrow eyebrow-light">{section}</p><h1>{title}</h1><p>{description}</p></div><aside class="page-banner-aside"><span>ECMEL TURİZM <i>·</i> İSTANBUL</span><b>2008</b><p>Yolculuğunuzun her adımında deneyimli bir ekip.</p><a href="/pages/iletisim.html">Bize ulaşın <i>↗</i></a></aside></div></section><section class="shell page-content"><div class="page-content-heading"><div><p class="eyebrow">ECMEL TURİZM / {section}</p><h2>{section_title}</h2></div>{'<a class="text-link" href="/pages/iletisim.html">Bilgi alın <span>↗</span></a>' if not item["children"] else ''}</div><div class="page-card-grid">{related_links(item)}</div>{culture_details}{highlights_html}{cookie_details}{contact_form}{review_content}<div class="page-contact-strip"><div><b>Bir sonraki adımı birlikte planlayalım.</b><span>0212 635 35 52 <i>·</i> info@ecmeltur.com</span></div><a href="/pages/iletisim.html">Ekibimizle görüşün <span>↗</span></a></div></section></main>
<footer class="footer"><div class="shell"><div class="footer-main"><div><a class="brand brand-footer" href="/index.html"><span class="brand-name">ECMEL<span>TURİZM</span></span></a><p>Hac, umre ve kültür turlarında<br>2008’den beri hizmetinizde.</p></div><div class="footer-column"><b>TURLAR</b><a href="/pages/umre.html">Umre</a><a href="/pages/hac.html">Hac</a><a href="/pages/kultur-turlari.html">Kültür turları</a><a href="/pages/yurtdisi-turlar.html">Yurtdışı turlar</a><a href="/pages/yurtici-turlar.html">Yurtiçi turlar</a></div><div class="footer-column"><b>HİZMETLER</b><a href="/pages/vize.html">Vize</a><a href="/pages/ucak-bileti.html">Uçak bileti</a><a href="/pages/otel.html">Otel</a><a href="/pages/sss.html">SSS</a><a href="/pages/blog.html">Blog</a></div><div class="footer-column footer-address"><b>ECMEL TURİZM</b><p>Kayabaşı Mah. Adnan Menderes Bulvarı<br>Kuzey Yakası Ofisleri, A1 Blok K:2 D:17<br>Başakşehir / İstanbul</p><a href="tel:+902126353552">0212 635 35 52</a><a href="mailto:info@ecmeltur.com">info@ecmeltur.com</a></div></div><div class="footer-bottom"><span>© 2026 Ecmel Turizm. Tüm hakları saklıdır.</span><span>A Grubu Seyahat Acentası · IATA</span><a href="/pages/cerez-politikasi.html">Gizlilik ve çerezler</a></div></div></footer><script src="/cms-public.js?v=verified-tour-content-20261023i"></script><script src="/script.js?v=premium-navigation-20261023"></script></body></html>'''
    rendered = rendered.replace('<span class="brand-name">ECMEL<span>TURİZM</span></span>', '<img class="brand-logo" src="../assets/ecmel-logo.png" alt="Ecmel Turizm">')
    return (rendered.replace('href="/pages/', 'href="../pages/')
            .replace('href="/index.html"', 'href="../index.html"')
            .replace('href="/styles.css"', 'href="../styles.css?v=premium-storefront-20261023b"')
            .replace('src="/cms-public.js?v=verified-tour-content-20261023i"', 'src="../cms-public.js?v=verified-tour-content-20261023i"')
            .replace('src="/script.js?v=premium-navigation-20261023"', 'src="../script.js?v=premium-navigation-20261023b"'))

# Generate only detail pages; index.html is maintained as the bespoke home page.
PAGES.mkdir(exist_ok=True)
for item in PAGES_DATA:
    (PAGES / f"{item['slug']}.html").write_text(page_html(item), encoding="utf-8")

