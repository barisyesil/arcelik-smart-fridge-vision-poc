# infra/ — AWS Altyapısı (CDK)

Tüm altyapı Python ile yazılmış tek bir AWS CDK stack'idir
([`stacks/fridge_stack.py`](stacks/fridge_stack.py)). `cdk deploy` ile kurulur,
`cdk destroy` ile tamamen silinir. Bölge sabittir: **eu-central-1 (Frankfurt)**.

![Mimari boru hattı](../docs/images/mimari-pipeline.png)

## Stack ne kuruyor

| # | Kaynak | Notlar |
|---|---|---|
| 1 | CloudWatch Log Grupları (×3) | Lambda'lar + API Gateway erişim logu, retention 7 gün |
| 2 | DynamoDB `fridge-main` | Provisioned 5/5, GSI1, TTL `expires_at`, Streams açık |
| 3 | SQS `fridge-extractor-dlq` | Başarısız çıkarımlar için ölü mektup kuyruğu, 14 gün |
| 4 | SSM parametre referansı | Gemini anahtarı; değer **elle** oluşturulur (aşağıda) |
| 5 | Lambda `fridge-api` / `fridge-extractor` | arm64, Python 3.12, VPC yok |
| 6 | S3 `fridge-raw-{hesap}` | Public access kapalı, SSE-S3, CORS, 30 gün lifecycle, olay bildirimi |
| 7 | HTTP API `fridge-api-gw` | 5 rota, throttling 5 rps / burst 10, CORS kısıtlı |
| 8 | Budget 5 USD | %80 ve %100 eşiklerinde e-posta alarmı |
| 9 | IAM rolleri (×2) | Kaynak bazlı, wildcard yok |

Deploy sonunda üç çıktı verilir: `ApiUrl`, `BucketName`, `TableName`. `ApiUrl`
web arayüzünün `VITE_API_URL` değeridir.

## Gereksinimler

- Node 20+ ve AWS CDK CLI (`npm i -g aws-cdk`)
- Python 3.12+ ve `pip install -r requirements.txt`
- AWS kimlik profili (`~/.aws/credentials` + `~/.aws/config`, region `eu-central-1`)
- IAM kullanıcısına deploy izinleri; Budget kaynağı için faturalama erişimi

> **Not:** CDK CLI, `cdk.json` içindeki `python app.py` komutunu çalıştırır.
> `aws-cdk-lib`'in `cdk` komutunu çalıştıran Python ortamında kurulu olması
> gerekir (sanal ortam kullanıyorsan `requirements.txt`'i o ortama kur).

## Deploy adımları

### 1. Konsolda, deploy'dan önce

**a. Faturalama erişimi** (yalnızca ilk kez): Budget kaynağı, IAM kullanıcısının
faturalama verisine erişimini gerektirir. Root kullanıcıyla:
`Account → IAM User and Role Access to Billing Information → Activate`.

**b. Gemini anahtarını Parameter Store'a yaz.** SecureString CloudFormation ile
oluşturulamaz (değer şifresiz olarak stack state'ine düşerdi); bu yüzden elle:

```bash
aws ssm put-parameter \
  --name /smartfridge/dev/gemini-api-key \
  --type SecureString \
  --value "GEMINI_ANAHTARIN" \
  --region eu-central-1
```

### 2. Lambda paketlerini derle

Docker gerektirmez; ARM64 / Python 3.12 wheel'lerini kilit dosyasından indirir.

```bash
python scripts/build_lambda_packages.py
```

Bu adım `infra/build/fridge-api` ve `infra/build/fridge-extractor` klasörlerini
üretir. Bu klasörler versiyonlanmaz (`.gitignore`); stack bunlar yoksa açık bir
hata ile durur.

### 3. Bootstrap ve deploy

```bash
cdk bootstrap
cdk deploy -c budget_alert_email=ekip@ornek.com
```

`budget_alert_email` her `synth`/`deploy`'da verilmelidir; kişisel adres git
geçmişine girmesin diye `cdk.json`'a gömülmemiştir.

### 4. Konsolda, deploy'dan sonra — CloudWatch alarmları

Log grupları stack'te tanımlıdır; alarmlar konsoldan kurulur. Önce bir SNS
konusu (`smartfridge-alarms`) oluşturup e-posta aboneliğini onayla, sonra şu
alarmları ekle (Period 5 dk, eksik veri = "iyi/breaching değil"):

| Metrik | Boyut | İstatistik | Eşik |
|---|---|---|---|
| Lambda Errors | `fridge-extractor` | Sum | > 5 |
| Lambda Throttles | `fridge-extractor` | Sum | > 0 |
| Lambda Duration | `fridge-extractor` | p95 | > 30000 ms |
| SQS ApproximateNumberOfMessagesVisible | `fridge-extractor-dlq` | Maximum | > 0 |

En kritik olan sonuncusudur: DLQ'da mesaj varsa iş kaybı var demektir.

## Uçtan uca doğrulama

```bash
echo "VITE_API_URL=<ApiUrl>" > ../web/.env
cd ../web && npm install && npm run dev   # http://localhost:5173
```

Bir gıda fotoğrafı yükle; `/aws/lambda/fridge-extractor` log grubunda
`extraction_completed` satırını gör, envanterde ürünün belirmesini bekle.

## Silme

```bash
cdk destroy
```

Tüm kaynaklar `removalPolicy=DESTROY` ile tanımlıdır; stack silindiğinde geride
kaynak kalmaz. SSM parametresi elle oluşturulduğu için elle silinir:

```bash
aws ssm delete-parameter --name /smartfridge/dev/gemini-api-key --region eu-central-1
```

## Tasarım notu — dairesel bağımlılık

S3 olay bildirimi extractor Lambda'ya bağımlıdır. Extractor'ın IAM politikası da
bucket'a erişir; ancak bu erişim `grant_read/grant_put` ile verilirse policy'ye
bucket'a bir `Fn::GetAtt` referansı gömülür ve `RawBucket → ExtractorFunction →
policy → RawBucket` döngüsü oluşur. Bu döngü `cdk synth` sırasında görünmez,
yalnızca CloudFormation changeset aşamasında "Circular dependency" hatası verir.
Bunu önlemek için bucket ARN'i hesap kimliğinden elle kurulur ve IAM statement'ı
`add_to_role_policy` ile bucket kaynağına referans vermeden yazılır.
