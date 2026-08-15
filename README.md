# personal-ai-dataset

Kişisel ve profesyonel bilgileri kaynaklarıyla birlikte yöneten; tarihsel olarak
sorgulanabilir, gizlilik kontrollü ve farklı AI yaklaşımları için yeniden
üretilebilir çıktılar hazırlamayı hedefleyen dataset pipeline projesidir.

Bu repository bir AI modeli eğitmez ve çalıştırmaz. Transformer, fine-tuning ve
RAG uygulamaları ayrı projelerde geliştirilir; bu proje yalnızca onların
kullanacağı doğrulanmış veri altyapısını sağlar.

> [!WARNING]
> Repository public olacak şekilde tasarlanmıştır. Gerçek CV, transkript,
> sertifika, SQLite veritabanı, export, secret veya başka kişisel verileri
> commit etmeyin. Bu alanlar `.gitignore` ile korunur.

## Mevcut durum

Aşağıdaki temel özellikler hazırdır:

- SQLite şeması: `persons`, `facts`, `sources` ve `fact_sources`
- Merkezi SQLite bağlantısı ve checksum korumalı numaralı migrations
- Kişi oluşturma ve listeleme CLI'ları
- Fact ekleme, güncel/tarihli sorgulama ve geçmiş sorgulama
- Çok değerli fact key'leri için çoğul sorgu
- Fact dönemini kapatma, deprecated yapma ve soft-delete
- Eski fact'i kapatıp yenisini atomik ekleyen supersede işlemi
- Duplicate, tarih çakışması, visibility, status ve confidence validasyonları
- Source ekleme, SHA-256 dosya hash'i ve duplicate source tespiti
- Source kayıtlarını silmeden devre dışı bırakma
- Fact ile source arasında çift yönlü provenance bağlantıları
- Core DB'den ayrı staging candidate veritabanı
- Core kurallarını kullanan dry-run candidate validation
- Audit korumalı approve/reject ve atomik core promotion
- Hash tabanlı, sürüm korumalı raw belge ingestion
- TXT, Markdown, CSV, JSON, HTML, DOCX ve PDF metin extraction
- Structured candidate bundle import
- Gizlilik kontrollü Transformer, fine-tuning ve RAG exporter'ları
- Gerçek veriye dokunmayan bellek içi testler

## Mimari

```text
RAW SOURCES
     |
     v
EXTRACTION
     |
     v
STAGING / CANDIDATES
     |
     v
VALIDATION / APPROVAL
     |
     v
PERSONAL CORE DATABASE
     |
     +----------------+----------------+
     |                |                |
     v                v                v
TRANSFORMER       FINE-TUNING         RAG
  EXPORT             EXPORT          EXPORT
```

`data/core/personal_data.db` doğrulanmış kişisel bilgiler için source of
truth'tur. Raw belgeler kaynak, staging kayıtları doğrulanmamış aday ve export
dosyaları yeniden üretilebilir çıktıdır.

## Gereksinimler

- Python 3.10 veya üzeri
- SQLite (Python standart kütüphanesiyle gelir)

PDF metin extraction için `pypdf` kullanılır. Diğer temel işlemler Python
standart kütüphanesiyle çalışır.

## Hızlı başlangıç

Repository'yi klonlayın ve proje kökünde çalışın:

```powershell
git clone https://github.com/Ramazan-yildirim/personal-ai-dataset.git
cd personal-ai-dataset
python -m pip install -r requirements.txt
```

Local veritabanını oluşturun:

```powershell
python scripts/init_db.py
python scripts/init_staging_db.py
```

Bu komutlar bekleyen numaralı migration'ları sırayla uygular. Tekrar
çalıştırılmaları güvenlidir; uygulanmış migration dosyası sonradan
değiştirilirse checksum kontrolü işlemi durdurur.

## Görsel kontrol merkezi

Tüm günlük işlemleri tek pencereden yönetmek için:

```powershell
python scripts/personal_ai_ui.py
```

Uygulama veritabanlarını idempotent biçimde hazırlar ve şu sekmeleri sunar:

- **Kişiler ve Manuel Bilgi:** kişi oluşturma, dosyalı/dosyasız kaynağa bağlı
  candidate girişi ve onaylanmış fact görünümü
- **Belgeler:** belge ingestion, extraction önizlemesi, manuel source ve
  structured candidate bundle import
- **Onay Merkezi:** pending/approved/rejected candidate listeleme, validate,
  approve ve gerekçeli reject
- **Export:** public-default Transformer, fine-tuning ve RAG çıktıları

Arayüz yalnızca tek giriş noktasıdır; doğrulanan `src/` servislerini çağırır.
Core'a doğrudan fact ekleme düğmesi yoktur. Yeni bilgiler önce candidate olur
ve yalnızca açık onaydan sonra core DB'ye geçer.

Kişiyi local veritabanına ekleyin. İsim interaktif olarak istenir ve kaynak
koduna yazılmaz:

```powershell
python scripts/create_person.py
```

Oluşturulan kişi ID'sini görmek için:

```powershell
python scripts/list_persons.py
```

## Fact kullanımı

Aşağıdaki örnekler sentetik değerler kullanır.

Bir fact ekleme:

```powershell
python scripts/add_fact.py 1 education class 3 --valid-from 2025-09-01 --valid-to 2026-06-30
```

Belirli bir tarihte geçerli tekil fact'i sorgulama:

```powershell
python scripts/get_fact.py 1 education class --as-of 2025-12-01
```

Fact geçmişini sorgulama:

```powershell
python scripts/get_fact_history.py 1 education class
```

Aynı key aynı anda birden çok değere sahip olabiliyorsa bunu açıkça belirtin:

```powershell
python scripts/add_fact.py 1 skill programming_language Python
python scripts/add_fact.py 1 skill programming_language JavaScript --allow-overlap
python scripts/get_facts.py 1 skill programming_language
```

Tek değerli açık uçlu bir fact'i yeni değerle değiştirme:

```powershell
python scripts/manage_fact.py supersede 1 4 --valid-from 2026-09-01
```

Varsayılan olarak eski kayıt yeni başlangıçtan bir gün önce kapatılır. Arada
bilinçli bir boşluk olacaksa eski bitiş tarihini açıkça verin:

```powershell
python scripts/manage_fact.py supersede 1 4 --valid-from 2026-09-01 --previous-valid-to 2026-06-30
```

Diğer yaşam döngüsü işlemleri:

```powershell
python scripts/manage_fact.py close 1 2026-06-30
python scripts/manage_fact.py deprecate 1
python scripts/manage_fact.py delete 1
```

`deprecated`, sonradan yanlış veya güvenilmez olduğu anlaşılan kayıtlar;
`deleted` ise audit amacıyla fiziksel olarak tutulan mantıksal silinmiş
kayıtlar içindir. Tarihsel olarak eski ama doğru kayıtlar `active` kalabilir.

## Source ve provenance kullanımı

Tercih edilen yöntem belgeyi ingestion komutuna vermektir. Komut belgeyi uygun
`data/raw/` alt klasörüne güvenli biçimde kopyalar, SHA-256 hash'ini hesaplar ve
source kaydını oluşturur:

```powershell
python scripts/ingest_document.py cv "Synthetic CV" C:\incoming\example_cv.pdf --source-date 2026-01-15
```

Dosya zaten raw klasöründeyse veya source kaydını kopyalama olmadan manuel
oluşturmak gerekiyorsa `add_source.py` kullanılabilir:

```powershell
python scripts/add_source.py cv "Synthetic CV" --file-path data/raw/cv/example_cv.pdf --source-date 2026-01-15
```

Dosyasız manuel beyan gibi bir kaynak da oluşturulabilir:

```powershell
python scripts/add_source.py manual "Synthetic statement" --source-date 2026-01-15
```

Kaynakları listeleme ve artık kullanılmayan bir kaynağı tarihçeden silmeden
devre dışı bırakma:

```powershell
python scripts/list_sources.py
python scripts/list_sources.py --active-only
python scripts/manage_source.py deactivate 1
```

Doğrulanmış fact ile source kaydını bağlama:

```powershell
python scripts/link_fact_source.py 1 1
python scripts/show_fact_source_links.py fact 1
python scripts/show_fact_source_links.py source 1
```

Inactive bir source veya deleted bir fact için yeni bağlantı kurulamaz. Daha
önce kurulmuş bağlantılar audit ve geçmiş sorguları için korunur.

## Belge extraction

Kayıtlı bir source belgesinden metin çıkarın:

```powershell
python scripts/extract_source.py 1
```

Çıktı `data/staging/extracted/` altında hash içeren yeniden üretilebilir bir
JSON dosyasına yazılır. Extraction öncesinde raw belgenin hash'i tekrar
doğrulanır; kayıt sonrasında değiştirilmiş belge işlenmez.

Desteklenen adaptörler:

- UTF-8/CP1254 TXT, Markdown ve CSV
- Deterministik JSON
- Görünür metni alan HTML
- Standart kütüphaneyle DOCX
- `pypdf` ile PDF

PNG/JPG dosyaları arşivlenebilir ancak OCR adaptörü henüz yoktur. Taranmış,
metin katmanı bulunmayan PDF belgeleri de OCR gerektirir.

## Staging candidate ve review akışı

Extraction sonucu bulunan doğrulanmamış bilgi doğrudan core DB'ye eklenmez.
Önce ayrı local `data/staging/candidates/candidates.db` veritabanına yazılır.

Kaynağa bağlı sentetik bir candidate oluşturma:

```powershell
python scripts/add_candidate.py 1 education class 4 --source-id 1 --valid-from 2026-09-01 --visibility private --confidence 0.9
```

Pending candidate kayıtlarını listeleme ve core kurallarıyla dry-run validation:

```powershell
python scripts/list_candidates.py --review-status pending
python scripts/manage_candidate.py validate 1
```

Candidate doğruysa onaylayın:

```powershell
python scripts/manage_candidate.py approve 1 --note "Belgeyle doğrulandı"
```

Onay işlemi fact'i core DB'ye ekler ve candidate'ın `source_id` alanı varsa
fact-source bağlantısını aynı transaction içinde kurar.

Candidate yanlışsa nedenini yazarak reddedin:

```powershell
python scripts/manage_candidate.py reject 1 --note "Tarih bilgisi hatalı"
```

Rejected candidate fiziksel olarak silinmez. Approved veya rejected bir kayıt
tekrar incelenemez; düzeltme gerekiyorsa yeni candidate oluşturulur.

### Structured candidate bundle import

Bu repository doğal dil belgesini yorumlayan bir LLM çalıştırmaz. Harici veya
kural tabanlı bir extraction aracı candidate önerilerini
`examples/candidate_bundle.example.json` formatında üretebilir. Bundle'ı
staging'e atomik ve idempotent biçimde alın:

```powershell
python scripts/import_candidates.py path\to\candidate_bundle.json
```

Aynı bundle tekrar import edilirse exact candidate kayıtları çoğaltılmaz.
Bundle içindeki tek bir kayıt yapısal olarak hatalıysa hiçbir kayıt eklenmez.
Import edilen candidate'lar yine validate ve manuel review aşamasından geçer.

## Dataset exportları

Tüm exporter'lar varsayılan olarak yalnızca `public` ve `active` fact'leri
kullanır. Private veya internal bilgi ancak açık komut bayrağıyla eklenir.

Transformer corpus:

```powershell
python scripts/export_datasets.py transformer
```

`personal_corpus.txt` yalnızca core personal fact'leri içerir.
`full_corpus.txt` buna `data/supplemental/transformer/` altındaki TXT/Markdown
corpuslarını ekler.

Fine-tuning chat JSONL:

```powershell
python scripts/export_datasets.py finetuning
```

Deterministik `train.jsonl`, `validation.jsonl` ve `test.jsonl` üretilir.

RAG documents ve chunks:

```powershell
python scripts/export_datasets.py rag
```

Tüm çıktıları birlikte yeniden üretmek için:

```powershell
python scripts/export_datasets.py all
```

Private fact'lerin bilinçli olarak gerektiği yalnızca local kullanımda:

```powershell
python scripts/export_datasets.py all --include-private
```

`--include-internal` daha hassastır ve normal model datasetlerinde
kullanılmamalıdır. Üretilen dosyalar `data/exports/` altında tutulur, Git'e
girmez ve source of truth değildir.

## Testler

```powershell
python -m unittest discover -s tests -v
```

Testler `:memory:` SQLite veritabanı ve tamamen sentetik veriler kullanır.
Local `data/core/personal_data.db` dosyasını değiştirmez.

## Proje yapısı

```text
data/
  core/                 Local SQLite source of truth
  raw/                  Orijinal kaynak belgeler
  staging/              Extracted ve candidate kayıtları
  supplemental/         Modele özel ek datasetler
  exports/              Yeniden üretilebilir model çıktıları
examples/               Yalnızca sentetik public örnekler
scripts/                İnce CLI katmanı
src/database/           Şema ve reusable database servisleri
tests/                  Sentetik otomatik testler
```

Kişisel veri klasörleri Git tarafından izlenmez. Public repository'de klasör
yapısını göstermek gerekirse yalnızca güvenli `.gitkeep` dosyaları kullanın.

## Temel veri kuralları

- Bilgileri atomik `category / key / value` fact'leri olarak saklayın.
- Tarihlerde ISO 8601 `YYYY-MM-DD` biçimini kullanın.
- `valid_from` ve `valid_to` sınır günleri geçerlidir.
- Açık uçlu dönem için `valid_to = NULL` kullanılır.
- Otomatik extraction sonucunu doğrudan core DB'ye yazmayın.
- Eski fact'i fiziksel olarak silmeyin.
- Gerçek kişisel veriyi kod, test veya public örneklere koymayın.
- Bir fact'i mümkün olduğunda kaynak kaydıyla ilişkilendirin.

## Mevcut sınırlar ve isteğe bağlı geliştirmeler

Çekirdek pipeline; ingestion, text extraction, staging review, core promotion
ve üç model export formatıyla uçtan uca hazırdır. Bilinen sınırlar:

1. PNG/JPG ve taranmış PDF belgeleri için OCR adaptörü yoktur.
2. Doğal dilden semantik candidate üretimi bu dataset repository'sinde model
   çalıştırmaz; ayrı extraction sistemi structured bundle üretmelidir.
3. Büyük datasetler için streaming exporter ve performans ölçümleri eklenebilir.

Katkı yapmadan önce mevcut kodu ve gizlilik sınırlarını inceleyin; minimum,
test edilebilir değişiklikleri tercih edin.
