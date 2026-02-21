---
name: k8s-netlab-development
description: Core development skill for K8S NetLab MVP project. Enforces production-grade code quality, prevents hallucinations, and ensures safe incremental development.
---

# K8S NetLab Development Skill

## Project Context

**Project**: K8S NetLab MVP  
**Timeline**: 2 weeks  
**Stack**: Python FastAPI + vanilla HTML/JS  
**Hardware**: Dell T430 (10C/20T, 80GB RAM)  
**Cost**: ~$26/month  

**Critical Lessons from Past Failures:**
- ChatGPT hallucinated non-existent functions
- Deleted global variables causing crashes
- Local changes broke entire codebase
- Security sacrificed for "quick wins"
- Generated toy code instead of production code

**This skill prevents ALL of these issues.**

---

## RULE 1: NO HALLUCINATIONS

### NEVER:
- ❌ Call functions that don't exist
- ❌ Use undefined variables
- ❌ Import non-installed modules
- ❌ Assume global state exists

### ALWAYS:
- ✅ Read files first before modifying
- ✅ Verify functions exist before calling
- ✅ Check imports in requirements.txt
- ✅ Document all global state

---

## RULE 2: ATOMIC MODIFICATIONS ONLY

**Always use precise replacements, never rewrite entire files:**

```python
# ✅ CORRECT - Precise modification
str_replace(
    path="vm.py",
    old_str="timeout=30",
    new_str="timeout=60"
)

# ❌ WRONG - Rewriting entire file
# This risks losing code!
```

**Benefits:**
- Only changes what needs changing
- Preserves all other code
- Easy to review
- Easy to revert

---

## RULE 3: SMALL INCREMENTAL STEPS

**Development workflow:**

```
Step 1: Single Feature (20-80 lines)
  → Write code
  → Test immediately
  → If works: Commit
  → If fails: Fix or revert

Step 2: Next Feature
  → Repeat

NEVER write 500+ lines without testing!
```

**Example:**
```
✅ Good approach:
  1. Write connect_proxmox() (30 lines) → Test ✅ → Commit
  2. Write create_vm() (50 lines) → Test ✅ → Commit
  3. Write delete_vm() (40 lines) → Test ✅ → Commit

❌ Bad approach:
  1. Write entire vm_manager.py (500 lines)
     → Test → 50 errors → Can't find bugs → 😭
```

---

## RULE 4: PRODUCTION CODE QUALITY

### Every function MUST include:

```python
def create_vm(vm_id: int, template_id: int) -> dict:
    """
    Create a new VM by cloning a template.
    
    Args:
        vm_id: ID for the new VM (100-999999)
        template_id: Template VM to clone from
        
    Returns:
        dict: {'success': bool, 'data': dict, 'error': str}
        
    Raises:
        ValueError: If vm_id is invalid
        ProxmoxAPIError: If VM creation fails
    """
    # 1. Input validation
    if not 100 <= vm_id <= 999999:
        raise ValueError(f"Invalid VM ID: {vm_id}")
    
    # 2. Logging
    logger.info(f"Creating VM {vm_id} from template {template_id}")
    
    # 3. Error handling
    try:
        result = proxmox.nodes('pve').qemu(template_id).clone.post(
            newid=vm_id,
            name=f"k8s-lab-{vm_id}"
        )
        logger.info(f"✓ VM {vm_id} created successfully")
        return {'success': True, 'data': result, 'error': None}
    except ProxmoxAPIError as e:
        logger.error(f"VM creation failed: {e}")
        return {'success': False, 'data': None, 'error': str(e)}
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
        return {'success': False, 'data': None, 'error': str(e)}
```

**Required elements:**
1. ✅ Type hints (params and return)
2. ✅ Docstring (Google style)
3. ✅ Input validation
4. ✅ Logging (info, error, critical)
5. ✅ Try/except/finally
6. ✅ Consistent return format

---

## RULE 5: SECURITY FIRST

### NEVER hardcode secrets:

```python
# ❌ WRONG - Security disaster!
PROXMOX_HOST = "192.168.1.10"
PROXMOX_PASSWORD = "supersecret123"
API_KEY = "sk-ant-api03-..."

# ✅ CORRECT - Use environment variables
import os

PROXMOX_HOST = os.getenv("PROXMOX_HOST")
PROXMOX_USER = os.getenv("PROXMOX_USER")
PROXMOX_PASSWORD = os.getenv("PROXMOX_PASSWORD")

if not all([PROXMOX_HOST, PROXMOX_USER, PROXMOX_PASSWORD]):
    raise RuntimeError("Missing required environment variables")
```

### Security checklist:
- [ ] No hardcoded passwords/API keys
- [ ] All inputs validated
- [ ] SQL injection prevented (use parameterized queries)
- [ ] Command injection prevented
- [ ] Rate limiting implemented
- [ ] Error messages don't leak sensitive info
- [ ] HTTPS enforced in production

---

## MODIFICATION PROTOCOL

### Before modifying ANY code:

**Step 1: READ the current file**
```python
# Use view tool to read existing code
view("/path/to/file.py")
```

**Step 2: UNDERSTAND the structure**
- What global variables exist?
- What functions are defined?
- What are the dependencies?
- What imports are present?

**Step 3: PLAN the change**
- Which exact lines will change?
- What is the scope of impact?
- Will this break anything else?

**Step 4: SHOW the diff**
```
--- Before (lines 25-30) ---
def create_vm(vm_id):
    return proxmox.create(vm_id)

+++ After (lines 25-35) +++
def create_vm(vm_id: int) -> dict:
    if not 100 <= vm_id <= 999999:
        raise ValueError(f"Invalid VM ID: {vm_id}")
    
    try:
        return {'success': True, 'data': proxmox.create(vm_id)}
    except Exception as e:
        logger.error(f"Failed: {e}")
        return {'success': False, 'error': str(e)}

Changes:
- Added type hints
- Added input validation
- Added error handling
- Added logging

Impact: Only create_vm() function
Risk: Low (isolated change)
```

**Step 5: GET user approval**

**Step 6: APPLY the change atomically**

**Step 7: REQUEST testing**
```
Change applied successfully.
Please run: pytest tests/test_vm.py -v
```

---

## FILE ORGANIZATION

### Modular architecture (small focused files):

```
backend/
├── config.py           # Environment config only (50 lines)
├── proxmox_api.py      # Proxmox API wrapper (150 lines)
├── vm_manager.py       # VM lifecycle management (200 lines)
├── api_routes.py       # FastAPI routes (180 lines)
├── websocket.py        # WebSocket terminal handler (120 lines)
├── models.py           # Pydantic models (100 lines)
└── utils.py            # Helper functions (80 lines)
```

**Benefits:**
- Clear separation of concerns
- Easy to understand
- Easy to test
- Changes are isolated
- No "ripple effect" bugs

---

## GIT WORKFLOW

### Required version control:

```bash
# ALWAYS commit working state before changes
git status
git add .
git commit -m "Working state: VM creation functional"

# Make your changes
# Test thoroughly

# If successful:
git add .
git commit -m "feat: add VM deletion with cleanup"
git push

# If failed:
git reset --hard HEAD  # Instant rollback to working state!
```

**Commit message format:**
```
feat: add new feature
fix: bug fix
refactor: code restructure
test: add tests
docs: update documentation
```

---

## TESTING REQUIREMENTS

### Every feature needs tests:

```python
# tests/test_vm_manager.py
import pytest
from backend.vm_manager import create_vm, delete_vm

def test_create_vm_success():
    """Test successful VM creation"""
    result = create_vm(vm_id=999, template_id=100)
    assert result['success'] == True
    assert 'data' in result
    assert result['error'] is None

def test_create_vm_invalid_id():
    """Test VM creation with invalid ID"""
    with pytest.raises(ValueError, match="Invalid VM ID"):
        create_vm(vm_id=-1, template_id=100)

def test_delete_vm_success():
    """Test successful VM deletion"""
    # First create
    create_vm(vm_id=999, template_id=100)
    # Then delete
    result = delete_vm(vm_id=999)
    assert result['success'] == True
```

**Run tests after every change:**
```bash
# Single file
pytest tests/test_vm_manager.py -v

# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=backend --cov-report=html
```

---

## ERROR HANDLING STANDARD

### Consistent error response format:

```python
from typing import Dict, Any, Optional

def standard_operation() -> Dict[str, Any]:
    """
    Standard pattern for all operations.
    
    Returns:
        {
            'success': bool,
            'data': Any (if success),
            'error': str (if failure)
        }
    """
    try:
        # Do operation
        result = perform_operation()
        
        logger.info("✓ Operation completed successfully")
        return {
            'success': True,
            'data': result,
            'error': None
        }
        
    except SpecificException as e:
        logger.error(f"Known error occurred: {e}")
        return {
            'success': False,
            'data': None,
            'error': str(e)
        }
        
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
        return {
            'success': False,
            'data': None,
            'error': f"Unexpected error: {str(e)}"
        }
```

**Never:**
- ❌ Use bare `except:`
- ❌ Silently fail
- ❌ Return inconsistent formats
- ❌ Let exceptions bubble up unhandled

---

## LOGGING STANDARDS

```python
import logging
from logging.handlers import RotatingFileHandler

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File handler with rotation
file_handler = RotatingFileHandler(
    'app.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    '%(levelname)s: %(message)s'
))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Usage
logger.debug("Detailed debug info")        # Development only
logger.info("Normal operation milestone")  # Important events
logger.warning("Unexpected but handled")   # Potential issues
logger.error("Operation failed")           # Errors
logger.critical("System failure")          # Critical errors
```

---

## CODE REVIEW CHECKLIST

**Before completing ANY code:**

```yaml
Code Quality:
  - [ ] Type hints on all functions
  - [ ] Docstrings (Google style)
  - [ ] No code duplication
  - [ ] Functions < 50 lines
  - [ ] Files < 300 lines

Safety:
  - [ ] Input validation
  - [ ] Error handling (try/except)
  - [ ] Logging at key points
  - [ ] No hardcoded secrets
  - [ ] No SQL/command injection

Testing:
  - [ ] Unit tests written
  - [ ] Tests pass
  - [ ] Edge cases covered
  - [ ] Coverage > 80%

Version Control:
  - [ ] Committed to git
  - [ ] Good commit message
  - [ ] Can rollback if needed

Documentation:
  - [ ] README updated
  - [ ] Comments for complex logic
  - [ ] Changelog updated
```

---

## PROJECT-SPECIFIC CONSTRAINTS

### K8S NetLab MVP Requirements:

**Technology Stack:**
```yaml
Backend:
  Language: Python 3.10+
  Framework: FastAPI
  VM Management: Proxmoxer
  Testing: pytest
  
Frontend:
  HTML/CSS/JS: Vanilla (no frameworks)
  Terminal: xterm.js (CDN)
  Styling: Tailwind CSS (CDN)

Infrastructure:
  Hypervisor: Proxmox VE
  VM OS: Ubuntu 22.04
  K8s: K3s (lightweight)
  Networking: Cloudflare Tunnel
  Reverse Proxy: Nginx
```

**Resource Constraints:**
```yaml
Hardware:
  Server: Dell T430
  CPU: 10 cores / 20 threads
  RAM: 80GB
  Storage: 2×1.8TB HDD

Limits:
  Concurrent VMs: 2-3 users
  VM Resources: 4 cores, 8GB RAM each
  Session Duration: 30 minutes (auto-cleanup)
  Monthly Cost: ~$26 (electricity only)
```

**MVP Scope (Must Have):**
```yaml
✅ Core Features:
  - VM create/clone from template
  - VM automatic deletion after 30min
  - Web-based terminal (xterm.js)
  - 3-4 basic K8s network experiments
  - Experiment documentation display
  - Command copy buttons

❌ NOT in MVP (Future versions):
  - User authentication/login
  - Database (use in-memory storage)
  - Progress saving
  - Payment/subscription system
  - Social features
  - Mobile optimization
  - Multiple concurrent experiments per user
```

---

## COMMUNICATION STYLE

### When proposing changes:

**✅ GOOD:**
```
I will modify backend/vm_manager.py:

Function: create_vm()
Lines: 45-52
Change: Add VM name validation
Impact: Only this function
Dependencies: None
Risk: Low

Diff:
[show before/after]

This change:
- Validates VM name format
- Returns clear error if invalid
- Doesn't affect other functions

Proceed with this change?
```

**❌ BAD:**
```
I rewrote the entire module. Here's 500 lines of new code...
```

### When uncertain:

**✅ GOOD:**
```
I'm not certain about the Proxmox API parameter format.

Options:
a) Test it experimentally in a safe way
b) Check Proxmox documentation first
c) Use a more conservative approach

Which would you prefer?
```

**❌ BAD:**
```
[Assumes something]
[Writes code]
[Code doesn't work]
```

---

## PRODUCTION DEPLOYMENT CHECKLIST

**Before deploying to production:**

```yaml
Security:
  - [ ] No secrets in code
  - [ ] Environment variables set
  - [ ] Input validation complete
  - [ ] Rate limiting enabled
  - [ ] HTTPS enforced
  - [ ] Security headers set

Reliability:
  - [ ] Error handling complete
  - [ ] Graceful degradation
  - [ ] Resource cleanup (finally blocks)
  - [ ] Timeout handling
  - [ ] Retry logic for transient failures

Observability:
  - [ ] Logging configured
  - [ ] Log rotation enabled
  - [ ] Health check endpoint
  - [ ] Metrics collection ready

Testing:
  - [ ] All unit tests pass
  - [ ] Integration tests pass
  - [ ] Manual testing complete
  - [ ] Performance tested (2-3 concurrent users)

Documentation:
  - [ ] README updated
  - [ ] API documented
  - [ ] Deployment guide written
  - [ ] Troubleshooting guide created
```

---

## SUMMARY

**This skill ensures:**
- ✅ No hallucinations (verify before using)
- ✅ No breaking changes (atomic modifications)
- ✅ Production-grade code (always)
- ✅ Security first (no shortcuts)
- ✅ Small safe steps (test frequently)
- ✅ Can always rollback (git workflow)

**Apply this skill to EVERY development task in K8S NetLab project.**

---

**Version**: 1.0  
**Last Updated**: 2024-02-15  
**Status**: Active  
**Author**: K8S NetLab Development Team
