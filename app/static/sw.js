self.addEventListener('push', function(event) {
    let data = { title: 'ОТК Сканер', body: 'Новое уведомление', url: '/' };
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        icon: '/static/favicon.ico', // если есть иконка, можно указать путь
        badge: '/static/favicon.ico',
        data: { url: data.url || '/' }
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const urlToOpen = event.notification.data.url || '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(windowClients) {
            // Если вкладка уже открыта — фокусируемся на ней
            for (let i = 0; i < windowClients.length; i++) {
                const client = windowClients[i];
                if (client.url.includes(urlToOpen) && 'focus' in client) {
                    return client.focus();
                }
            }
            // Иначе открываем новую
            if (clients.openWindow) {
                return clients.openWindow(urlToOpen);
            }
        })
    );
});