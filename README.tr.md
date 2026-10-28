# EPLAN Yapay Zekâ Otomasyon Araç Seti

[English](README.md) · [Español](README.es.md) · [Deutsch](README.de.md) · [中文](README.zh-CN.md) · [한국어](README.ko.md) · **Türkçe** · [Polski](README.pl.md) · [Русский](README.ru.md)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Canary-ECAD/eplan-mcp)
[![MCP Badge](https://lobehub.com/badge/mcp/covagashi-eplan_2026_ia_mcp_scripts)](https://lobehub.com/mcp/covagashi-eplan_2026_ia_mcp_scripts)

Model Context Protocol (MCP) üzerine kurulu, **EPLAN Electric P8** ve **EPLAN EEC Pro 2026**
için yapay zekâ destekli otomasyon.

📖 **Belgeler, kurulum kılavuzu ve tüm araçların başvuru kaynağı: [covaga.dev](https://covaga.dev)** (İngilizce)

Bu depo, çalışan bir EPLAN örneğini yöneten yerel MCP sunucusunu içerir. Üç uzak belge RAG'i ayrı
[eplan-cloudflare-rags](https://github.com/Canary-ECAD/eplan-cloudflare-rags) deposunda bulunur.

> Burada bir LLM ile mi çalışıyorsunuz? [`llm.md`](llm.md) dosyasını okuyun: araç setinin
> yapabildiği ve yapılandırılabilen her şeyi LLM'e yönelik bir dille anlatır.

## Depo yapısı

```
.
└── eplan-p8-mcp-server/          # YEREL: EPLAN P8'i yöneten MCP sunucusu
```

| Bileşen | Tür | Amaç | EPLAN ürünü |
|---|---|---|---|
| `eplan-p8-mcp-server/` | Yerel Python MCP | Çalışan EPLAN'ı Claude'dan yönetmek: proje açma/kapama, dışa aktarma, raporlar, betikler | EPLAN Electric P8 |
| [**eplan-cloudflare-rags**](https://github.com/Canary-ECAD/eplan-cloudflare-rags) | Uzak Cloudflare Workers, ayrı depo | P8 2026, P8 2027 ve EEC Pro belgelerini MCP ve REST üzerinden sunmak | EPLAN Electric P8 ve EEC Pro |
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Claude Code becerisi, ayrı depo | Claude'a doğru EPLAN betikleri, API kodu ve Remote Client uygulamaları yazmayı öğretmek | EPLAN Electric P8 |

Her deponun kurulum ve kullanım ayrıntılarını içeren kendi README dosyası vardır.

## MCP nedir?

**MCP (Model Context Protocol)**, yapay zekâ asistanlarının harici araçlar ve hizmetlerle
etkileşime girmesini sağlayan açık bir standarttır. Claude yalnızca kod üretmekle kalmaz;
EPLAN içinde gerçek zamanlı olarak işlem *yürütebilir* ve belgelere arama yoluyla başvurabilir.

## Hızlı başlangıç

### Yerel EPLAN otomasyonu (P8)

```bash
pip install pythonnet "mcp<2"
claude mcp add eplan -- python YOLUNUZ/eplan-p8-mcp-server/mcp_server/server.py
claude mcp list   # "eplan" listelenmeli
```

Ardından EPLAN'ı başlatın, Claude Code'u açın ve `connect to eplan` deyin. Kılavuzun tamamı
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md) dosyasındadır.

![Yapılandırılmış Claude CLI](assets/claude-cli-configured.png)

#### Ön koşul

Sunucunun bağlanabilmesi için EPLAN'da uzaktan erişim açık olmalıdır: **Dosya → Ayarlar… → İş
istasyonu → Arayüzler → Uzaktan erişim** altında **Remote Client üzerinden uzaktan erişime izin
ver** seçeneğini etkinleştirin.

![Remote Client üzerinden uzaktan erişime izin ver](assets/remoting-allow-local-access.png)

#### Sunucunun sunduğu araçlar

Varsayılan `full` modunda sunucu **199 araç** yayınlar:

| Grup | Sayı | Kapsamı |
|---|---|---|
| Bağlantı / yardımcı | 8 | Bağlanma, sürüm seçimi, durum, uzantıları listeleme |
| Tipli EPLAN işlemleri (`eplan_*`) | 183 | Belgelenmiş ya da doğrulanmış her işlem için bir araç; her biri QuietMode altında bir C# betiği içinde sessizce çalışır, böylece hiçbir EPLAN iletişim kutusu gözetimsiz bir çalıştırmayı durduramaz |
| İşlem kataloğu (`eplan_action_catalog` / `_describe` / `_run` / `_ribbon_catalog`) | 4 | Yalnızca arayüz düğmesi olarak var olan yaklaşık 1.050 işleme daha erişir; bunlar resmî belgelerden değil, kurulumdaki `MFTools.xml` dosyasından çıkarılmıştır |
| Asset Administration Shell (`aas_*`) | 4 | AAS/AASX dijital ikiz dışa ve içe aktarımı |

Yaklaşık 1.050 katalog işlemine bilerek *ayrı ayrı* sarmalayıcı araç verilmedi: bu, araç sayısını
üç katına çıkarır ve diğer her şey için araç seçimini kötüleştirirdi.

183 tipli aracın dördü canlı DataModel araçlarıdır —
`eplan_live_query_functions`, `eplan_live_query_pages`, `eplan_live_set_function_text`
ve `eplan_live_set_connection_designations` —; açık projenin nesne modelini çalışma zamanı
yansıması (reflection) ile okuyup düzenler ve betik motorunun statik `using` yönergeleriyle ilgili
kısıtlamasını aşar.

Tekil işlemlerin ötesinde araç seti, tamamen gözetimsiz bir geliştir → dağıt → test et döngüsünün
yapı taşlarını da kapsar:

- **Uygulama yaşam döngüsü** — `eplan_app_launch` / `eplan_app_shutdown` /
  `eplan_app_restart`: EPLAN'dan çıkma, eklenti DLL'lerini değiştirme, yeniden başlatma, yeniden
  bağlanma, projeyi yeniden açma.
- **Kullan-at test projeleri** — `eplan_scratch_project_*`: bir şablondan klonlanan geçici projeler.
- **Tanılama** — `eplan_get_system_messages`: EPLAN'ın mesaj ağacını okuyup kullanıcının arayüzde
  gördüğü hataların ve uyarıların aynısını görme.
- **Özel uzantı modülleri** — [aşağıya](#özel-uzantı-modülleri-eplan_mcp_extensions) bakın.

Bu deponun docstring'lerinden üretilen araç araç başvuru kaynağı
[covaga.dev/docs/tools](https://covaga.dev/docs/tools/project-and-workspace-management/) adresindedir.

#### Discovery modu

`EPLAN_MCP_MODE=discovery`, 199 yerine 13 araç yayınlar; çok token tüketen bir araç listesini,
görev başına bir ek arama turuyla takas eder. Her istekte tüm araçların tam şemasını gönderen MCP
istemcileri için buna değer.

**Claude Code'da kullanmayın.** Claude Code araç şemalarını zaten kendisi erteler — önce bir ad
listesi, şema ise gerektiğinde —; bu yüzden 199 araçlık `full` listesi ona neredeyse `discovery`
modunun 13 aracı kadar az mal olur ve üstüne ara → açıkla → çağır dolaylılığını eklemek yalnızca
bir tur daha ekler. Ödünleşim ve ölçümler
[`eplan-p8-mcp-server/mcp_server/README.md`](eplan-p8-mcp-server/mcp_server/README.md#discovery-mode-eplan_mcp_mode)
dosyasındadır.

### Uzak belge RAG'leri (P8, EEC Pro, 2027)

Zaten dağıtılmış ve kullanıma hazır — yerel veri gerekmez:

```bash
# EPLAN Electric P8 belgeleri (2026, anlamsal arama)
claude mcp add eplan-rag -- cmd /c npx mcp-remote https://rag2026.covaga.xyz/mcp

# EPLAN EEC Pro 2026 belgeleri
claude mcp add eecpro-rag -- cmd /c npx mcp-remote https://rageecpro.covaga.xyz/mcp

# EPLAN Electric P8 belgeleri (2027, anahtar kelime / tam metin arama)
claude mcp add eplan-wiki-2027 -- cmd /c npx mcp-remote https://rag2027.covaga.xyz/mcp
```

`eplan-wiki-2027`, `eplan-rag`'in 2026'dan 2027'ye yükseltilmiş hâli değil, bilerek ayrı tutulmuş
bir sunucudur: farklı bir belge sürümünü dizinler *ve* farklı bir arama yöntemi kullanır
(Vectorize + bge anlamsal arama yerine,
[`cloudflare-rag-eplan-2027/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-eplan-2027)
içindeki wiki üzerinde SQLite FTS5/bm25 anahtar kelime eşleştirmesi). Gerçek sorgularla yan yana
ölçüldüğünde farklı yerlerde başarısız olurlar: tam ad aramalarında ("X'in imzası nedir")
FTS5 kazanır, sorgu belgelerle hiç ortak kelime paylaşmadığında anlamsal arama kazanır. İkisini de kurun.

İkisi de geliştirme sırasında EPLAN işlem adlarını ve parametrelerini doğrulamak için kullanışlı
basit bir REST API sunar:

```bash
curl -X POST https://rag2026.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "export project pdf", "topK": 3}'

curl -X POST https://rag2027.covaga.xyz/search -H "Content-Type: application/json" \
     -d '{"query": "FindAction", "topK": 3}'
```

Araçlar, REST uç noktaları ve mimari için
[`cloudflare-rag-eplan-p8/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eplan-p8/README.md) ve
[`cloudflare-rag-eecpro/README.md`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/blob/main/cloudflare-rag-eecpro/README.md) dosyalarına bakın.

### Görsel sembol RAG'i (yeni)

EPLAN elektrik sembollerini görüntülerden tanıyın: bir PDF'ten, şemadan ya da ekran görüntüsünden
kırpılmış sembol girer, gerçek `short_name` çıkar:

- Dizin: CLIP ViT-B/32 (512 boyut, kosinüs) ile gömülmüş 33.502 EPLAN sembol görüntüsü (IEC/NFPA),
  Cloudflare Vectorize'da; kaynak:
  [`covaga/electrical-symbols-dataset`](https://huggingface.co/datasets/covaga/electrical-symbols-dataset).
- Herkese açık uç nokta `https://symbols.covaga.xyz` (diğer RAG'lerle aynı açık model, kimlik
  bilgisi gerekmez):

```bash
# vector = sembol görüntüsünün L2 normalize edilmiş CLIP ViT-B/32 gömmesi
curl -X POST https://symbols.covaga.xyz/query -H "Content-Type: application/json" \
     -d '{"vector": [0.01, -0.02, "...512 floats..."], "topK": 5}'
```

Her eşleşme `short_name`, katalog `number`, `description` ve `variant_id` ile bir kosinüs puanı
içerir; `short_name`, EPLAN API çağrılarının beklediği tanımlayıcıdır. Yeniden dizinleme ve yeniden
dağıtım,
[`cloudflare-rag-symbols/`](https://github.com/Canary-ECAD/eplan-cloudflare-rags/tree/main/cloudflare-rag-symbols)
içindeki GitHub Actions ile yapılır.

#### Bu MCP sunucusundan kullanma

Hazır bir uzantı
[`eplan-p8-mcp-server/extensions/symbol_search.py`](./eplan-p8-mcp-server/extensions/symbol_search.py)
içinde gelir. Etkinleştirdiğinizde ajan `eplan_symbol_search` aracını kazanır:

```powershell
pip install sentence-transformers pillow requests
set EPLAN_MCP_EXTENSIONS=<repo>\eplan-p8-mcp-server\extensions
```

Ardından kırpılmış bir sembol görüntüsü verildiğinde Claude
`eplan_symbol_search(image_path="C:\\...\\crop.png")` çağrısını yapar → görüntü yerelde CLIP ile
gömülür → `symbols.covaga.xyz`, `F1 (no. 50, variant B) — Fuse, single-pole` gibi adaylar döndürür
→ en iyi `short_name` EPLAN API çağrılarında kullanılır. Cloudflare belirteci gerekmez: dizin
bağlantısını Worker tutar.

### EPLAN geliştirme için Claude Code becerisi

MCP sunucuları Claude'un EPLAN üzerinde *işlem yapmasını* sağlar.
[**eplan-scripting**](https://github.com/Canary-ECAD/eplan-scripting-skill) becerisi ise ona
*doğru EPLAN kodu yazmayı* öğretir: betik giriş noktaları, doğrulanmış işlem parametreleri, parça
veritabanı erişimi, Remote Client otomasyonu (dinamik portlar, arayüzsüz EPLAN, Cogineer) ve üretim
ortamının tuzakları — sözde asenkron komut engellemesi, mesaj döngüsü izleme iş parçacığı, dispose
disiplini, EPLAN 2025 uzaktan erişim değişiklikleri.

Beceri kendi deposunda yaşar ve bilerek **ortamdan bağımsızdır**: herhangi bir MCP sunucusu, belirli
bir betik çalıştırıcı ya da belirli bir belge dizini varsaymaz; bu yüzden buradaki diğer şeyleri
kullansanız da kullanmasanız da tek başına işe yarar.

```
/plugin marketplace add Canary-ECAD/eplan-mcp
/plugin install eplan@eplan-tools            # yönlendirici + P8 becerisi + P8 belge RAG'leri
/plugin install eplan-scripting@eplan-tools  # yalnızca Electric P8
/plugin install eec-pro@eplan-tools          # yalnızca EEC Pro
```

Elle kurulum ve ayrıntılar:
[becerinin README dosyası](https://github.com/Canary-ECAD/eplan-scripting-skill#readme).

## Yeni EPLAN işlemleri ekleme

Yerel MCP sunucusu araçları her işlem paketinin `__all__` listesinden **dinamik olarak** kaydeder;
bu yüzden bir işlem eklemek iki adım sürer ve araç başına kalıp kod gerektirmez.

### 1. İşlemi uygulayın

`eplan-p8-mcp-server/mcp_server/api/actions/<modülünüz>.py` içinde:

```python
def open_project(project_path: str, open_mode: str = None) -> dict:
    """Open a project in EPLAN.

    Args:
        project_path: Full path to the .elk project file.
        open_mode: "Standard", "ReadOnly", or "Exclusive" (optional).
    """
    manager, error = _get_connected_manager()
    if error:
        return error
    action = _build_action("ProjectOpen", Project=project_path, OpenMode=open_mode)
    return manager.execute_action(action)
```

### 2. Dışa aktarın

Fonksiyonu `eplan-p8-mcp-server/mcp_server/api/actions/__init__.py` içindeki import'lara **ve**
`__all__` listesine ekleyin. Ardından otomatik olarak `eplan_open_project` adıyla kaydedilir.

### 3. MCP sunucusunu yeniden başlatın

Yeni araç, Claude veya sunucu yeniden başladığında kullanılabilir olur.

### 4. Resmî belgelerle doğrulayın (isteğe bağlı)

`eplan-p8-mcp-server/tools/validate_actions.py`, sarmalayıcılarda tanımlanan her işlem adını ve
parametresini resmî EPLAN belge RAG'i ile karşılaştırır ve markdown bir rapor yazar:

```bash
python eplan-p8-mcp-server/tools/validate_actions.py
```

![EPLAN testi](assets/eplan-test.png)

### İpuçları

1. **Belgelerle doğrulayın.** EPLAN işleminin tam adını ve parametrelerini doğrulamak için uzak
   P8 RAG'ini (`https://rag2026.covaga.xyz`) kullanın.
2. **Anlamlı docstring'ler ve tür ipuçları yazın.** Bunlar, LLM'in gördüğü ve güvendiği araç
   açıklamasına ve girdi şemasına dönüşür.
3. **Yollara dikkat edin.** Windows yollarında kaçış karakteri (`\\`) ya da düz eğik çizgi (`/`) gerekir.

## Özel uzantı modülleri (`EPLAN_MCP_EXTENSIONS`)

Sunucu, **bu deponun dışından ek araç modülleri** yükleyebilir: herkese açık bir depoda
bulunmaması gereken şirkete özel ya da özel araçlar (kendi eklentileriniz için test düzenekleri,
iç iş akışları).

`EPLAN_MCP_EXTENSIONS` ortam değişkenini bir veya daha fazla klasöre yönlendirin (Windows'ta `;`
ile ayrılır). Oradaki, adı `_` ile başlamayan her üst düzey `*.py` dosyası başlangıçta içe aktarılır
ve `__all__` içindeki fonksiyonları yerleşik işlemler gibi MCP aracı olarak kaydedilir:

```python
# my_company_tools.py  (özel bir depoda, eplan-mcp içinde DEĞİL)
TOOL_PREFIX = "acme_"          # isteğe bağlı, varsayılan "eplan_"
__all__ = ["run_smoke_test"]

import actions                  # sunucunun api/ klasörü sys.path üzerinde
from actions._base import _get_connected_manager

def run_smoke_test(project_path: str) -> dict:
    """Docstring becomes the tool description the LLM sees."""
    clone = actions.scratch_project_create(project_path)
    ...
    return {"success": True}
```

Kurallar ve davranış:

- `TOOL_PREFIX` araçlara bir ad alanı verir (yukarıda `acme_run_smoke_test`).
- Uzantılar, yerleşik işlemlerin kullandığı her şeyi içe aktarabilir: `actions`, `actions._base`,
  `actions.scripted._execute_script` (EPLAN içinde C# çalıştırma), `eplan_connection`.
- Bozuk bir uzantı stderr'e bildirilir ve atlanır; sunucunun başlamasını asla engellemez.
- `eplan_list_extensions` neyin yüklendiğini gösterir.

Yaşam döngüsü ve kullan-at proje araçlarıyla birlikte bu, özel EPLAN eklentileri geliştirmek için
tamamen gözetimsiz bir döngü sağlar: DLL'i derle → dağıt → `eplan_app_restart` → eklentinin
işlemlerinin kaydedildiğini doğrula (örneğin bir `FindAction` betiğiyle) → onları kullan-at bir
projede çalıştır → EPLAN'ın şikâyet ettiği her şeyi yakalamak için `eplan_get_system_messages`.

## EPLAN sürüm seçimi (otomatik)

**Yapılandırılacak bir şey yok.** Başlangıçta sunucu `C:\Program Files\EPLAN\Platform` altındaki
kurulu sürümleri tarar ve:

- **Otomatik mod (varsayılan):** `eplan_connect` **en yeni kurulu sürümü** hedefler ve uygun .NET
  çalışma zamanını kendisi seçer — EPLAN 2027+ için coreclr, 2026 ve öncesi için .NET Framework.
- **Açık mod:** LLM, kurulu olanları listelemek için `eplan_versions` çağırabilir ve ardından
  `eplan_connect(version="2026")` ile belirli bir sürüme bağlanabilir — örneğin "connect to eplan 2026".

Notlar:

- EPLAN standart olmayan bir yere mi kurulu? `EPLAN_PLATFORM_ROOT` değişkenini onun `Platform`
  klasörüne ayarlayın.
- Bir sürümün DLL'leri sürece yüklendikten sonra sürüm değiştirmek MCP sunucusunu yeniden başlatmayı
  gerektirir — bir .NET çalışma zamanı çalışırken değiştirilemez.
- `eplan_connect`, başka bir makinedeki EPLAN örneğine ulaşmak için `host` (ve `"host:port"`) da
  kabul eder; port otomatik algılama yalnızca localhost'ta çalışır.

## İlgili depolar

| Depo | Nedir |
|---|---|
| [**eplan-scripting-skill**](https://github.com/Canary-ECAD/eplan-scripting-skill) | Yukarıdaki Claude Code becerisi; bağımsız ve ortamdan bağımsız. `/plugin marketplace add Canary-ECAD/eplan-mcp` ile kurun. |
| [**eplan-ctxmenu-kit**](https://github.com/covagashi/eplan-ctxmenu-kit) | EPLAN'ın sağ tık menülerine kendi girdilerinizi ekleyin ve kullanıcının tıkladığı satırı okuyun. Bir keşif aracı ve eksiksiz bir örnek. |

## Kaynaklar

- [EPLAN API belgeleri](https://www.eplan.help/)
- [MCP protokol belirtimi](https://modelcontextprotocol.io/)
- [Claude Code belgeleri](https://docs.anthropic.com/claude-code)

## Lisans

MIT — bkz. [`LICENSE`](LICENSE).

> **Uyarı:** Bu, [Canary E-cad](https://github.com/Canary-ECAD) tarafından yürütülen bağımsız bir topluluk projesidir. EPLAN GmbH & Co. KG ile bağlantılı değildir, onun tarafından onaylanmamış veya desteklenmemektedir. EPLAN, EPLAN Electric P8 ve EPLAN EEC Pro, ilgili sahibinin ticari markalarıdır.
