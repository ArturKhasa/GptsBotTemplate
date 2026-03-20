ACTIVE_SUBSCRIPTIONS = {
    'buy_subscription_lite' : {
        'name': 'Lite',
        'price' : 2990 ,
        'description' : 'Подпика Lite ответы на любые вопросы, урезанные расшифровки, есть лимит',
        'payload' : 'lite'
    },
    'buy_subscription_pro' : {
        'name': 'Pro',
        'price': 3980,
        'description': 'Подпика Pro развернутые ответы, поиск в интернете, поиск по файлам, есть лимит',
        'payload': 'pro'
    },
    'buy_one_time': {
        'name': 'Разовый',
        'price': 350,
        'description': 'Разовый доступ к боту',
        'payload': 'one-time'
    },
}

class Sub:
    price = None
    description = None
    payload = None

    def __init__(self, price, description, payload):
        self.price = price
        self.description = description
        self.payload = payload


def get_subscription_info(buy_subscription_lite):
    sub_info = ACTIVE_SUBSCRIPTIONS[buy_subscription_lite]
    sub = Sub(price=sub_info['price'], description=sub_info['description'], payload=sub_info['payload'])

    return sub
