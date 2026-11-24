# Deploying on AWS

This puts the whole prototype (the API, the three demo stations, the ops dashboard and the network map) on one EC2
server with Docker. It takes about 15 minutes.

**What was tested:** steps 3 to 6 and the backup command, run with Docker on a copy of this code. They covered the
build, the start, reading `deploy.env`, Reset demo data with the sales history, a restart that keeps the data, and a
backup. The AWS console steps, RDS, HTTPS and monitoring follow standard AWS and Docker practice but were not tried.

**What runs:** one container with the app on port 8000, published on the server's port 80. The data is a SQLite file
in a Docker volume, so it survives restarts and rebuilds. Amazon RDS (PostgreSQL) works too; see
[Using Amazon RDS](#using-amazon-rds-postgresql-instead-of-sqlite).

## 1. Launch a server

In the EC2 console, launch an instance:

| Setting | Value |
| --- | --- |
| Image | Ubuntu Server 24.04 LTS |
| Type | `t3.small` (2 GB of memory) |
| Storage | 20 GB |
| Security group, inbound | SSH (22) from your own IP; HTTP (80) from anywhere |

Do not open ports 3000, 5432, 8000 or 9090 to the internet. Then connect: `ssh ubuntu@<public IP>`.

## 2. Install Docker

Use Docker's own packages: the compose file needs Docker Compose 2.24 or newer.

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

Connect again (so the group change applies) and check: `docker compose version` should print 2.24 or higher.

## 3. Get the code and set it up

```bash
git clone https://github.com/agastya-nath123/CSL559_CSD_Group_Project.git darkstore
cd darkstore
cp deploy.env.example deploy.env
sed -i "s/^JWT_SECRET=$/JWT_SECRET=$(openssl rand -hex 32)/" deploy.env
```

`deploy.env` holds the server's settings, and each one is explained inside the file. The `sed` line fills in
`JWT_SECRET`, the random secret that signs staff logins. It is the one setting that must not be left empty. The
defaults are those of the team's hosted copy: the site on port 80, SQLite, and 20 requests a second per customer.
`deploy.env` is git-ignored; never commit it.

## 4. Start it

```bash
docker compose --env-file deploy.env up -d --build
curl http://localhost/health
```

The first build takes a few minutes. `{"status":"ok"}` means the app is up. Always pass `--env-file deploy.env`, so
the settings in that file are used.

## 5. Load the demo data once

The first start loads the shops, stock and staff accounts, but no sales history. Open `http://<public IP>/`, scroll
to **Store ops desk** and press **Reset demo data** once. It also writes 60 days of sales and the delivery lookups, so
the forecasts, the KPIs and the network map have data.

## 6. Check it

| Page | Address |
| --- | --- |
| The three stations (customer, picker, store ops) | `http://<public IP>/` |
| Ops dashboard | `http://<public IP>/ops.html` |
| Picker phone screen | `http://<public IP>/picker.html` |
| Store network map | `http://<public IP>/network.html` |
| API reference | `http://<public IP>/docs` |

A quick end-to-end check: as the customer, add two items, press **Hold my items** and then **Pay now**. On the picker
handheld press **Get next order**. The stock table on the ops desk changes as you go.

## Things to know

- **It is a public demo.** Every demo account, `admin` included, uses the password `demo`, and the pages log in with
  it themselves. So anyone who opens the site can also press **Reset demo data**. Do not put real data in it.
- **Run one copy of the app.** Timed jobs, the stock cache and the rate limit live inside the process. Two copies
  would both reorder stock and split the rate limit. For more capacity, pick a bigger instance; do not add an Auto
  Scaling group or a second container.
- **Plain HTTP is fine.** The pages do not need HTTPS. For HTTPS, see the next section.

## Optional: HTTPS with a load balancer

1. Request a certificate for your domain in AWS Certificate Manager.
2. Create an Application Load Balancer with an HTTPS (443) listener using that certificate, forwarding to a target
   group with the instance on port 80. Point your domain at the load balancer.
3. Change the instance's security group so port 80 accepts traffic **only from the load balancer's security group**.
4. Add this line to `deploy.env` and run the `up` command from step 4 again:

   ```
   FORWARDED_ALLOW_IPS=*
   ```

   Behind a load balancer every request seems to come from it, so all customers would share one rate-limit allowance.
   This setting makes the app read the customer's real address from the `X-Forwarded-For` header. It is only safe
   because of step 3; otherwise anyone could fake that header.

## Using Amazon RDS (PostgreSQL) instead of SQLite

1. Create an RDS PostgreSQL 16 database in the same VPC. Its security group must allow port 5432 from the EC2
   instance's security group.
2. In `deploy.env`, uncomment `DARKSTORE_DB` and fill in the endpoint, user, password and database name:

   ```
   DARKSTORE_DB=postgresql://USER:PASSWORD@your-db.xxxxxxxx.REGION.rds.amazonaws.com:5432/darkstore
   ```

   If the password has characters such as `@`, `:` or `/`, percent-encode them (`@` is `%40`).
3. Run the `up` command from step 4 again, then do step 5. The app creates its tables in an empty database and
   upgrades an existing one when it starts. The team's CI runs every test on PostgreSQL.

## Optional: monitoring (Prometheus and Grafana)

Add `GRAFANA_ADMIN_PASSWORD=<a password>` to `deploy.env`, then:

```bash
docker compose --env-file deploy.env --profile monitoring up -d --build
```

Both listen on the server itself only. To view Grafana from your laptop, open a tunnel with
`ssh -L 3000:localhost:3000 ubuntu@<public IP>` and browse to http://localhost:3000. It opens on the *Dark store*
dashboard. Leave `METRICS_TOKEN` empty in this setup, because the bundled Prometheus scrapes `/metrics` without one.

## Day to day

| Task | Command (in the `darkstore` folder) |
| --- | --- |
| Follow the log | `docker compose --env-file deploy.env logs -f app` |
| Update to the newest code | `git pull && docker compose --env-file deploy.env up -d --build` |
| Back up the SQLite data | `docker compose --env-file deploy.env exec app python -c "import sqlite3; s=sqlite3.connect('/data/darkstore.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"` then `docker compose --env-file deploy.env cp app:/data/backup.db ./backup.db` |
| Stop (data kept) | `docker compose --env-file deploy.env down` |
| Stop and delete all data | `docker compose --env-file deploy.env down -v` |

Updating keeps the data, and any new database migration runs on its own when the app starts. Take a backup first.
