import pdfkit
from config import DADATA_API_KEY
import json
import aiohttp
import datetime
ART_RUS_DETAILS = {
    "name": "ООО \"АРТРУС\"",
    "inn": "1655163150",
    "kpp": "165501001",
    "address": "420107, Татарстан Респ, г Казань, ул Спартаковская, д. 23, офис 5",
    "phone": "+79872966569",
    "bik": "049205770",
    "bank": "АКБ \"Энергобанк\" (АО) г. Казань",
    "rs": "40702810800150110916",
    "ks": "30101810300000000770"
}

async def get_company_info(inn: str):
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    headers = {
        "Authorization": f"Token {DADATA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = json.dumps({"query": inn})

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=payload) as response:
            if response.status == 200:
                data = await response.json()
                if data["suggestions"]:
                    return data["suggestions"][0]["data"]
    return None


async def generate_invoice(company_info, chat_id):
    day = datetime.date.today().day
    month = datetime.date.today().month
    year = datetime.date.today().year
    invoice_html = f"""
    <html>
    <head><meta charset='utf-8'></head>
    <body>
        <h2>Счет на оплату № {chat_id} от {day}.{month} 2025 г.</h2>
        <p><b>Поставщик:</b> {ART_RUS_DETAILS['name']}, ИНН {ART_RUS_DETAILS['inn']}, КПП {ART_RUS_DETAILS['kpp']}, {ART_RUS_DETAILS['address']}, тел.: {ART_RUS_DETAILS['phone']}</p>
        <p><b>Банк получателя:</b> {ART_RUS_DETAILS['bank']}</p>
        <p><b>БИК:</b> {ART_RUS_DETAILS['bik']}, <b>Р/с:</b> {ART_RUS_DETAILS['rs']}, <b>К/с:</b> {ART_RUS_DETAILS['ks']}</p>
        <hr>
        <p><b>Покупатель:</b> {company_info['name']['full_with_opf']}, ИНН {company_info['inn']}, КПП {company_info['kpp']}</p>
        <p><b>Адрес:</b> {company_info['address']['unrestricted_value']}</p>
        <hr>
        <table border='1' cellpadding='5' cellspacing='0'>
            <tr><th>№</th><th>Товары (работы, услуги)</th><th>Кол-во</th><th>Ед.</th><th>Цена</th><th>Сумма</th></tr>
            <tr><td>1</td><td>Услуги по предоставлению консультации, "Бухгалтер GPT"</td><td>4</td><td>ед</td><td>1 000,00</td><td>4 000,00</td></tr>
        </table>
        <h3>Итого: 4 000,00 руб.</h3>
        <p><b>Без налога (НДС):</b> -</p>
        <h3>Всего к оплате: 4 000,00 руб.</h3>
        <p><b>Всего наименований:</b> 1, на сумму 4 000,00 руб.</p>
        <p><b>Четыре тысячи рублей 00 копеек</b></p>
        <p>Оплатить не позднее {day}.{month}.{year}</p>
        <p>Оплата данного счета означает согласие с условиями предоставляемой услуги/товара.</p>
        <p>Услуга/товар предоставляется по факту прихода денег на р/с Поставщика.</p>
        <p>Руководитель: _______________  Бухгалтер: _______________</p>
    </body>
    </html>
    """

    pdf_path = "invoice.pdf"
    config = pdfkit.configuration(wkhtmltopdf='/usr/bin/wkhtmltopdf')  # Проверьте путь
    pdfkit.from_string(invoice_html, pdf_path, configuration=config)
    return pdf_path