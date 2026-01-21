# Feast MinIO Setup - Changes Explanation

## 🎯 Problem Statement

When running `feast apply` with MinIO (local S3-compatible storage), Feast was throwing an error:
```
OSError: AWS Error ACCESS_DENIED during HeadBucket operation: No response body
```

This happened because:
1. **PyArrow** (used by Feast to read S3 files) was trying to connect to AWS S3 instead of local MinIO
2. PyArrow wasn't configured for **path-style addressing** (MinIO requires this, not virtual-hosted style)
3. PyArrow wasn't using the correct **endpoint** (localhost:9000) or **credentials**
4. Environment variables needed to be set **before** Feast/PyArrow initialized

---

## 🔧 Changes Made

### 1. Created `minio_config.py` - Automatic MinIO Configuration

**File:** `feature_repo/minio_config.py`

**Purpose:** This module automatically configures all MinIO settings when imported.

**What it does:**

#### A. Sets Environment Variables (Lines 25-44)
```python
os.environ["AWS_ENDPOINT_URL"] = "http://localhost:9000"  # Tell PyArrow where MinIO is
os.environ["AWS_S3_ENDPOINT"] = "http://localhost:9000"    # Alternative endpoint variable
os.environ["AWS_S3_ADDRESSING_STYLE"] = "path"             # Path-style addressing (required!)
os.environ["ARROW_S3_USE_PATH_STYLE"] = "1"                # PyArrow-specific path-style flag
os.environ["AWS_S3_USE_HTTPS"] = "0"                       # Use HTTP, not HTTPS
os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"             # MinIO credentials
os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"         # MinIO credentials
os.environ["AWS_REGION"] = "us-east-1"                     # Required (ignored by MinIO)
```

**Why these are needed:**

- **AWS_ENDPOINT_URL**: Redirects PyArrow from AWS S3 (`s3.amazonaws.com`) to your local MinIO (`localhost:9000`)
- **Path-style addressing**: MinIO uses path-style (`s3.amazonaws.com/bucket/key`) instead of virtual-hosted style (`bucket.s3.amazonaws.com/key`)
- **HTTP vs HTTPS**: Local MinIO typically runs on HTTP, not HTTPS
- **Credentials**: Even for local MinIO, authentication is required

#### B. Configures boto3 Default Session (Lines 46-76)
```python
boto3.setup_default_session(
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
    region_name='us-east-1',
)
```

**Why:** PyArrow sometimes uses boto3 under the hood, so we configure boto3's default session to use MinIO credentials.

#### C. Auto-execution (Line 79)
```python
setup_minio_env()  # Runs automatically when module is imported
```

**Why:** This ensures environment variables are set **before** any Feast or PyArrow code runs.

---

### 2. Updated `feature_views.py` - Added MinIO Configuration Import

**File:** `feature_repo/feature_views.py`

**Changes:**

#### A. Import minio_config at the top (Line 3)
```python
import minio_config  # noqa: F401 - Imported for side effects (env var setup)
```

**Why:** 
- This import runs **before** any Feast components are imported
- It ensures environment variables are set before PyArrow tries to connect to S3
- The `# noqa: F401` tells linters it's okay that we don't directly use the module (we import it for its side effects)

#### B. Added `s3_endpoint_override` to FileSource (Line 32)
```python
driver_events = FileSource(
    path="s3://ridematch-raw/",
    timestamp_field="timestamp",
    file_format=ParquetFormat(),
    s3_endpoint_override="http://localhost:9000",  # ← NEW: Tells Feast/PyArrow where MinIO is
)
```

**Why:**
- `s3_endpoint_override` is a **direct parameter** that Feast's FileSource accepts
- This explicitly tells PyArrow to use `localhost:9000` instead of AWS S3
- Combined with environment variables, this ensures PyArrow connects to MinIO correctly

#### C. Added Documentation Comments (Lines 17-26)
Explains why MinIO configuration is needed and how it works.

---

### 3. Fixed `entities.py` - Added Value Types

**File:** `feature_repo/entities.py`

**Changes:**
```python
# BEFORE:
driver = Entity(name="driver_id", join_keys=["driver_id"])

# AFTER:
from feast.value_type import ValueType
driver = Entity(name="driver_id", join_keys=["driver_id"], value_type=ValueType.STRING)
```

**Why:**
- Feast 0.40+ requires `value_type` to be explicitly specified (prevents deprecation warnings)
- `ValueType.STRING` indicates that `driver_id` is a string identifier
- This is a best practice and will be mandatory in future Feast versions

---

### 4. Updated `apply_feast.sh` - Conda Environment Support

**File:** `feature_repo/apply_feast.sh`

**Changes:**
```bash
# Activate conda environment
if command -v conda &> /dev/null; then
    eval "$(conda shell.bash hook 2>/dev/null)"
    conda activate ridematch
fi

# Run feast apply
feast apply
```

**Why:**
- Ensures the correct Python environment is used (`ridematch` conda environment)
- The conda environment has all required dependencies (feast, pyarrow, boto3, redis)
- Simpler script since `minio_config.py` handles all MinIO setup automatically

---

### 5. Installed Missing Dependencies

**Action:** Installed `redis` in the `ridematch` conda environment

**Why:**
- Your `feature_store.yaml` specifies Redis as the online store
- Feast needs the `redis` Python package to connect to Redis
- Without it, Feast couldn't even start because it tried to import the Redis online store module

---

## 🔄 How It Works Together

### Execution Flow:

1. **You run `feast apply`** (or `./apply_feast.sh`)

2. **Feast loads `feature_views.py`**
   - First line imports `minio_config`
   - `minio_config` sets all environment variables immediately
   - boto3 default session is configured

3. **Feast creates FileSource**
   - `s3_endpoint_override="http://localhost:9000"` tells PyArrow where MinIO is
   - Environment variables provide credentials and path-style addressing settings

4. **PyArrow connects to MinIO**
   - Reads `AWS_ENDPOINT_URL` → connects to `localhost:9000`
   - Reads `ARROW_S3_USE_PATH_STYLE` → uses path-style addressing
   - Reads `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` → authenticates
   - Reads `AWS_S3_USE_HTTPS` → uses HTTP (not HTTPS)

5. **Feast successfully reads from `s3://ridematch-raw/`** ✅

---

## 📊 Key Concepts Explained

### Path-Style vs Virtual-Hosted Style Addressing

**Virtual-Hosted Style (AWS S3 default):**
```
https://bucket-name.s3.amazonaws.com/path/to/file.parquet
```

**Path-Style (MinIO requires this):**
```
https://s3.amazonaws.com/bucket-name/path/to/file.parquet
```

MinIO doesn't support virtual-hosted style addressing, so we must force path-style.

### Why Environment Variables?

PyArrow's S3FileSystem reads configuration from:
1. **Environment variables** (checked first)
2. **boto3 default session** (fallback)
3. **Direct parameters** (if provided)

Since Feast creates the S3FileSystem internally, we can't pass parameters directly. So we use environment variables + `s3_endpoint_override` parameter.

---

## ✅ Result

Now when you run `feast apply`:

```
✅ No ACCESS_DENIED errors
✅ Successfully connects to MinIO at localhost:9000
✅ Reads from s3://ridematch-raw/ correctly
✅ Registers entities: driver_id, rider_id
✅ Registers feature views: driver_status, driver_agg
✅ No manual environment variable exports needed
```

---

## 🚀 Usage

### Option 1: Use the wrapper script
```bash
cd feature_repo
./apply_feast.sh
```

### Option 2: Run directly (with conda activated)
```bash
conda activate ridematch
cd feature_repo
feast apply
```

Both methods work because `minio_config.py` automatically sets up MinIO configuration when `feature_views.py` is imported!

