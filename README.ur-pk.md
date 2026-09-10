# ZeusAgent

یہ Nous Research / Hermes Agent پر مبنی ایک آزاد ذاتی AI ایجنٹ ہے۔ اصل MIT لائسنس اور انتساب [LICENSE](LICENSE) اور [NOTICE.md](NOTICE.md) میں محفوظ ہیں۔

یہ زیرِ ترقی سورس پیکیج ہے۔ تنصیب اور استعمال کی مرکزی رہنمائی [README.md](README.md) میں ہے۔

## اس پیکیج سے تنصیب

پورا ZIP نکالیں۔ Python 3.11–3.13 درکار ہے۔ انٹرفیس بنانے کے لیے `package.json` کے مطابق Node.js اور npm بھی درکار ہیں۔

```sh
python scripts/setup_zeus.py --web
python scripts/launch_zeus.py setup
python scripts/launch_zeus.py
```

Linux/macOS پر `python3` استعمال کیا جا سکتا ہے۔ Windows پر پہلے `KUR-ZEUS.bat` اور بعد میں `BASLAT-ZEUS.bat` چلائیں۔

ڈیسک ٹاپ کے لیے:

```sh
python scripts/setup_zeus.py --desktop
python scripts/launch_zeus.py --desktop
```

عام آغاز مقامی طور پر تیار کردہ ایپ چلاتا ہے۔ کوڈ کی تیاری کے دوران `--desktop-dev` استعمال کریں۔ ویب پینل کے لیے `python scripts/launch_zeus.py dashboard` چلائیں۔

ماڈل سروس اور Telegram الگ ترتیب دیں۔ پرانا Hermes ڈیٹا خودکار طور پر منتقل نہیں ہوتا۔ ZeusAgent کا اپنا ریموٹ اپ ڈیٹ چینل ابھی موجود نہیں؛ Hermes کے انسٹالر اصل پروڈکٹ نصب کرتے ہیں۔

وراثت میں ملنے والا پرانا ترجمہ [docs/UPSTREAM-README.ur-pk.md](docs/UPSTREAM-README.ur-pk.md) میں تاریخی حوالے کے طور پر محفوظ ہے۔
