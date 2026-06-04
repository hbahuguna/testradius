# TestSquad Troubleshooting Runbook

## Quick Diagnostics

### Check Service Status
```bash
# Check if containers are running
docker-compose ps

# Check logs
docker-compose logs core
docker-compose logs ui
```

### Common Issues

## Issue: Container Won't Start

### Symptom
```
Error: Container exits immediately
```

### Diagnosis
1. Check logs:
   ```bash
   docker-compose logs core
   ```

2. Common causes:
   - Missing environment variables
   - Database connection failure
   - Port already in use

### Fix
1. Set required environment variables:
   ```bash
   export DATABASE_URL=postgresql+asyncpg://testsquad:password@db:5432/testsquad
   export NEO4J_PASSWORD=testsquad_password
   ```

2. Check port availability:
   ```bash
   lsof -i :8000
   ```

3. Restart services:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

---

## Issue: Neo4j Connection Failed

### Symptom
```
ModuleNotFoundError: No module named 'neo4j'
```
or
```
Cannot connect to Neo4j: bolt://neo4j:7687
```

### Diagnosis
```bash
# Check Neo4j is running
docker-compose ps neo4j

# Check Neo4j logs
docker-compose logs neo4j
```

### Fix
1. Wait for Neo4j to be ready (has healthcheck)
2. Verify credentials in environment
3. Reset Neo4j data:
   ```bash
   docker-compose down -v  # WARNING: Deletes all data
   docker-compose up -d
   ```

---

## Issue: No Mappings Found

### Symptom
Mapping matrix shows empty or "No mappings found"

### Diagnosis
1. Check if files were indexed:
   ```bash
   # In Neo4j browser
   MATCH (s:Symbol) RETURN count(s)
   ```

2. Check if tests were indexed:
   ```bash
   MATCH (t:TestSymbol) RETURN count(t)
   ```

### Fix
1. Run sync to index files:
   ```
   POST /projects/{project_id}/sync
   ```

2. Run mapping:
   ```
   POST /projects/{project_id}/map-tests
   ```

---

## Issue: Export CSV Fails

### Symptom
Clicking "Export CSV" does nothing or returns 500 error

### Diagnosis
```bash
docker-compose logs core | grep pandas
```

### Fix
1. Rebuild container:
   ```bash
   docker-compose build core
   docker-compose up -d core
   ```

2. If still failing, check Neo4j has mappings:
   ```bash
   MATCH (s:Symbol)-[r:SUGGESTED_TEST]->(t:TestSymbol) RETURN count(r)
   ```

---

## Issue: Slow Performance

### Symptom
- Mapping takes very long
- Impact analysis times out

### Diagnosis
1. Check Neo4j indexes:
   ```cypher
   SHOW INDEXES
   ```

2. Check system resources:
   ```bash
   docker stats
   ```

### Fix
1. Create indexes:
   ```cypher
   CREATE INDEX symbol_name FOR (s:Symbol) ON (s.name)
   CREATE INDEX test_name FOR (t:TestSymbol) ON (t.name)
   ```

2. Reduce batch size in config
3. Use smaller symbol sets for testing

---

## Issue: UI Not Loading

### Symptom
- http://localhost:5173 shows blank
- Console errors about API

### Fix
1. Check API is running:
   ```bash
   curl http://localhost:8000/health
   ```

2. Update API URL in UI:
   ```bash
   # Rebuild UI
   cd ui && npm run build
   ```

---

## Issue: WebSocket Errors

### Symptom
```
WebSocket connection failed
```

### Fix
1. Check proxy settings:
   - nginx should pass `Upgrade` and `Connection` headers
2. Use correct protocol: `ws://` not `http://`

---

## Performance Tuning

### Increase Neo4j Heap Memory
In `docker-compose.yml`:
```yaml
neo4j:
  environment:
    - NEO4J_dbms_memory_heap_max__size=2G
```

### Enable Query Logging
```cypher
CALL db.logs.query.run() YIELD *
```

---

## Health Check Commands

### 1. API Health
```bash
curl http://localhost:8000/health
```

### 2. Database Health
```bash
docker-compose exec db pg_isready
```

### 3. Neo4j Health
```bash
curl http://localhost:7474
```

---

## Rollback Procedures

### Previous Version
```bash
git checkout <previous-tag>
docker-compose build
docker-compose up -d
```

### Clear All Data
```bash
docker-compose down -v
docker-compose up -d
```

---

## Contact

For issues not covered here:
- Check GitHub issues
- Review container logs with `--tail=100`