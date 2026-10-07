# Public websites / Публичные сайты

These are read-only views of an experimental local devnet, not a public
production blockchain. The edge is 192.168.0.13; origins stay on 192.168.0.100.

| Domain | LAN origin |
| --- | --- |
| https://computechain.space/ | http://192.168.0.100:8080/ |
| https://docs.computechain.space/ | http://192.168.0.100:8008/ |
| https://explorer.computechain.space/ | http://192.168.0.100:4000/ |

DNS A records point to 78.29.35.87. HTTP redirects to HTTPS except HTTP-01
validation. No www alias is configured. Mail TXT/MX records are unchanged.
Grafana/Prometheus stay LAN-only; native RPC/ABCI and explorer internals stay
loopback. Gateways reject public writes and do not proxy arbitrary native RPC.

## Updating origins

Run from the parent workspace, using the stand's Python environment:

```bash
.tools/blockchain-venv/bin/python computechain/scripts/web_services.py explorer up --trusted-proxy 192.168.0.13
.tools/blockchain-venv/bin/python computechain/scripts/web_services.py website up --trusted-proxy 192.168.0.13
python3 docs/stack.py up --site-url https://docs.computechain.space/
```

Settings persist outside Git. Later core `start_test.sh ...-up` commands retain
them. UI updates do not restart the blockchain. Config updates test/reload the
owned gateways. The website retains LAN links locally and domain links publicly;
Grafana is omitted on the public domain.

## Edge Nginx and certificates

Templates are in deploy/nginx/. The HTTP vhost lives in
/etc/nginx/sites-available/computechain.conf and is symlinked into sites-enabled.
Port 443 already belongs to a **TCP SNI router**. Add only these three domain
names to its existing map, forwarding to 127.0.0.1:8443. TLS terminates in the
new name-based vhosts on that loopback listener. Do not replace the SNI default
or existing routes. Always back up, run nginx -t and reload, never blind-restart.

The certificate contains exactly the three names. Its isolated Certbot config
directory is /etc/letsencrypt-computechain; accounts/ links to the edge's existing
ACME accounts. Keys never leave the edge or enter Git. Shared Certbot hooks are
not run: they include unrelated service restarts.

The installed certbot-computechain.timer checks twice daily with randomized
delay. Only a successful renewal tests/reloads Nginx; other services are untouched.
Inspect on the edge:

```bash
systemctl status certbot-computechain.timer
journalctl -u certbot-computechain.service
certbot renew --cert-name computechain.space --dry-run --config-dir /etc/letsencrypt-computechain --work-dir /var/lib/letsencrypt-computechain --logs-dir /var/log/letsencrypt-computechain --no-directory-hooks
```

The current stream proxy does not preserve public client IPs. Public explorer
visitors share the LAN gateway's API rate quota; per-client quotas require a
separate reviewed PROXY-protocol design, not a global change to other vhosts.
LAN HTTP remains trusted-network access; NAT is not an authentication boundary.

## Кратко по-русски

Три сайта работают по HTTPS через edge .13, содержимое остаётся на .100.
Это только интерфейсы локального devnet. Grafana и привилегированные API не
публикуются. Команды выше обновляют сайты без рестарта цепи и сохраняют настройки.
Для сертификата есть отдельный timer: чужие renewal hooks не запускаются.
Не менять общие маршруты SNI, почтовые записи или чужие сайты. Бэкапы конфигов
на edge находятся в /root/computechain-proxy-backups/; ключей в Git нет.
