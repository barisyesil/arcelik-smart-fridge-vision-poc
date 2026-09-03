# docs/images/

README dosyaları buradaki görsellere referans verir. Aşağıdaki iki dosyayı bu
klasöre ekle (adlar birebir aynı olmalı, yoksa görseller README'de görünmez):

| Dosya | İçerik | Nerede kullanılıyor |
|---|---|---|
| `faz1-akis-diyagrami.png` | Yüksek seviye akış diyagramı (web → API → S3 → extractor → DynamoDB/Gemini/DLQ) | Ana `README.md` |
| `mimari-pipeline.png` | Numaralı, servis-servis ayrıntılı boru hattı | Ana `README.md` ve `infra/README.md` |

PNG veya SVG kullanılabilir; SVG tercih edilirse README'lerdeki `.png`
uzantılarını `.svg` olarak güncelle. Ekran görüntüsü değil, dışa aktarılmış
(export) temiz diyagram önerilir.
