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

İlk geliştirme aşamasında aşağıdaki özellikler hazırdır:

- SQLite şeması: `persons`, `facts`, `sources` ve `fact_sources`
- Merkezi SQLite bağlantısı
- Kişi oluşturma ve listeleme CLI'ları
- Fact ekleme, güncel/tarihli sorgulama ve geçmiş sorgulama
- Çok değerli fact key'leri için çoğul sorgu
- Fact dönemini kapatma, deprecated yapma ve soft-delete
- Eski fact'i kapatıp yenisini atomik ekleyen supersede işlemi
- Duplicate, tarih çakışması, visibility, status ve confidence validasyonları
- Source ekleme, SHA-256 dosya hash'i ve duplicate source tespiti
- Source kayıtlarını silmeden devre dışı bırakma
- Fact ile source arasında çift yönlü provenance bağlantıları
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

Şu anda harici Python bağımlılığı yoktur.

## Hızlı başlangıç

Repository'yi klonlayın ve proje kökünde çalışın:

```powershell
git clone https://github.com/Ramazan-yildirim/personal-ai-dataset.git
cd personal-ai-dataset
```

Local veritabanını oluşturun:

```powershell
python scripts/init_db.py
```

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

Kaynak belgesini önce uygun `data/raw/` alt klasörüne yerleştirin. Dosyanın
SHA-256 hash'i ekleme sırasında otomatik hesaplanır:

```powershell
python scripts/add_source.py cv "Synthetic CV" --file-path data/raw/cv/example_cv.txt --source-date 2026-01-15
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

## Yol haritası

1. Validation ve staging candidate sistemi
2. Raw document ingestion
3. Manuel candidate onay/red akışı
4. Transformer exporter
5. Fine-tuning exporter
6. RAG exporter

Katkı yapmadan önce mevcut kodu ve gizlilik sınırlarını inceleyin; minimum,
test edilebilir değişiklikleri tercih edin.
