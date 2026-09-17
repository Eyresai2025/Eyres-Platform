from app_core.audit import verify_audit_integrity
ok, message, records = verify_audit_integrity()
print(f"{'PASS' if ok else 'FAIL'}: {message}; records={records}")
raise SystemExit(0 if ok else 2)
