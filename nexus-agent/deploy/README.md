# Production Deployment Guide

Deploy Nexus Agent to Kubernetes with the provided manifests.

---

## Architecture

```
User Browser
    |
    ├──> Ingress (nginx) ──> Frontend (nginx, port 80)
    |                           └──> Backend API (port 8000)
    └──> WebSocket ──────────> Backend API (port 8000)
                                    |
                                    ├──> PostgreSQL + pgvector
                                    └──> Redis 7
```

---

## Prerequisites

- **Kubernetes** 1.28+
- **kubectl** configured for your cluster
- **Ingress controller** (nginx-ingress recommended)
- **cert-manager** (for automatic SSL certificates)
- **Prometheus** + **Grafana** (optional, for monitoring)

---

## Quick Start

```bash
# Create namespace
kubectl create namespace nexus

# Apply all manifests
kubectl apply -n nexus -f deploy/k8s/

# Monitor rollout
kubectl -n nexus get pods -w
```

---

## Kubernetes Manifests

| File | Purpose |
|------|---------|
| `deployment.yaml` | Backend API server (2 replicas, health checks, resource limits) |
| `service.yaml` | Cluster-internal service on port 80 |
| `ingress.yaml` | External HTTP/HTTPS routing with TLS termination |
| `configmap.yaml` | Non-sensitive environment variables |
| `secret.yaml` | Sensitive values (credentials, master key) |
| `hpa.yaml` | Horizontal pod autoscaler (CPU-based, 2–10 replicas) |
| `pdb.yaml` | Pod disruption budget (min 1 available) |
| `network-policy.yaml` | Ingress/egress traffic restrictions |
| `migration-job.yaml` | One-shot Alembic DB migration job |

---

## Ingress Configuration

### TLS with cert-manager

Update `ingress.yaml` with your domain:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: nexus-agent
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - nexus.example.com
      secretName: nexus-tls
  rules:
    - host: nexus.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: nexus-agent
                port:
                  number: 80
```

### WebSocket Support

For chat WebSocket to work behind the ingress, ensure the controller
supports WebSocket upgrades (default with nginx-ingress).

---

## Secret Management

### Built-in Secrets (kubectl)

```bash
# Create the secret
kubectl create secret generic nexus-secrets \
  -n nexus \
  --from-literal=NEXUS_CREDENTIAL_MASTER_KEY="$(openssl rand -base64 32)"
```

### External Secrets Operator (recommended for production)

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: nexus-secrets
spec:
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: nexus-secrets
  data:
    - secretKey: NEXUS_CREDENTIAL_MASTER_KEY
      remoteRef:
        key: nexus/backend/master-key
```

### Token Rotation

1. Rotate `NEXUS_CREDENTIAL_MASTER_KEY` every 180 days

---

## Horizontal Pod Autoscaling

The HPA scales between 2 and 10 replicas based on CPU at 70% target.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: nexus-agent
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

### Custom Metrics (Advanced)

For Prometheus-based autoscaling, add:

```yaml
    - type: Pods
      pods:
        metric:
          name: nexus_active_sessions
        target:
          type: AverageValue
          averageValue: 500
```

---

## Database Migration Strategy

### Option 1: Pre-deploy Job (default)

The `migration-job.yaml` runs Alembic migrations as a one-shot Job
before the deployment rolls out:

```bash
kubectl apply -n nexus -f deploy/k8s/migration-job.yaml
kubectl wait -n nexus --for=condition=complete job/nexus-migrations --timeout=120s
kubectl apply -n nexus -f deploy/k8s/deployment.yaml
```

### Option 2: Init Container

Add an init container to the deployment:

```yaml
initContainers:
  - name: run-migrations
    image: nexus-agent:latest
    command: ["alembic", "upgrade", "head"]
    envFrom:
      - configMapRef:
          name: nexus-config
      - secretRef:
          name: nexus-secrets
```

### Rollback Procedure

```bash
# 1. Revert to previous deployment
kubectl rollout undo -n nexus deployment/nexus-agent

# 2. Roll back the database
alembic downgrade -1
```

---

## Redis Cluster Setup

### Option 1: Redis Sentinel (Recommended)

```yaml
# Connection format for Redis Sentinel
NEXUS_REDIS__URL=redis://sentinel-0:26379,sentinel-1:26379,sentinel-2:26379
```

### Option 2: Redis Cluster

```yaml
# Connection format for Redis Cluster
NEXUS_REDIS__URL=redis://redis-cluster-0:6379,redis-cluster-1:6379,redis-cluster-2:6379
```

Deploy using the Bitnami Helm chart:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm upgrade --install redis-cluster bitnami/redis-cluster \
  --set cluster.nodes=3 \
  --set cluster.replicas=1
```

---

## Monitoring Stack

### Prometheus

Add the following to your Prometheus configuration to scrape Nexus Agent:

```yaml
scrape_configs:
  - job_name: 'nexus-agent'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
```

The deployment already includes the necessary annotations:

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8000"
  prometheus.io/path: "/metrics"
```

### Grafana Dashboards

| Dashboard | Grafana ID | Description |
|-----------|------------|-------------|
| FastAPI | 19211 | Request rate, latency, errors |
| asyncpg | 15860 | Connection pool, query performance |
| Python Runtime | 11856 | Memory, GC, thread count |

### Alerts (PrometheusRule)

```yaml
groups:
  - name: nexus-agent
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Nexus Agent error rate > 5%"
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency > 5s"
      - alert: PodDown
        expr: kube_pod_status_phase{namespace="nexus",phase="Running"} < 2
        for: 1m
        labels:
          severity: critical
```

---

## Backup and Disaster Recovery

### PostgreSQL Backup

```bash
# Manual backup
kubectl exec -n nexus deployment/postgres -- pg_dump -U nexus nexus > nexus_backup_$(date +%Y%m%d).sql

# Automated cron backup (using K8s CronJob)
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nexus-db-backup
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: pg-dump
              image: pgvector/pgvector:pg16
              command:
                - sh
                - -c
                - pg_dump -h $PGHOST -U nexus nexus | gzip > /backups/nexus_$(date +%Y%m%d).sql.gz
              env:
                - name: PGHOST
                  value: postgres
                - name: PGPASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: nexus-secrets
                      key: NEXUS_DATABASE__PASSWORD
              volumeMounts:
                - name: backup-volume
                  mountPath: /backups
          restartPolicy: OnFailure
          volumes:
            - name: backup-volume
              persistentVolumeClaim:
                claimName: nexus-backup-pvc
```

### Redis Persistence

Redis is configured with RDB snapshots every 5 minutes (default). For
AOF persistence, add to the Redis configuration:

```
appendonly yes
appendfsync everysec
```

### Restore Procedure

```bash
# 1. Scale down the application
kubectl scale -n nexus deployment/nexus-agent --replicas=0

# 2. Restore PostgreSQL
kubectl exec -n nexus deployment/postgres -- psql -U nexus -d nexus -f /tmp/backup.sql

# 3. Restore Redis (if needed)
kubectl exec -n nexus deployment/redis -- redis-cli FLUSHALL
kubectl exec -n nexus deployment/redis -- redis-cli RESTORE <backup_key> 0 <dump_value>

# 4. Scale back up
kubectl scale -n nexus deployment/nexus-agent --replicas=2
```

### Disaster Recovery Checklist

| Step | Action | Expected Duration |
|------|--------|-------------------|
| 1 | Detect outage (monitoring alert) | < 1 min |
| 2 | Assess scope (DB vs Redis vs app) | 2-5 min |
| 3 | Scale app to 0 | < 30 s |
| 4 | Restore DB from latest backup | 5-30 min |
| 5 | Verify DB integrity | 2-5 min |
| 6 | Scale app back up | < 30 s |
| 7 | Verify health endpoints | < 1 min |
| 8 | Verify user-facing functionality | 2-5 min |

---

## Environment Variables

All configuration is documented in [.env.example](../.env.example).
Override any variable in the `configmap.yaml` or `secret.yaml` as needed.

### Build Args

| Arg | Default | Description |
|-----|---------|-------------|
| `NEXUS_FRONTEND__API_URL` | `http://localhost:8000` | Backend URL for frontend connectivity |
