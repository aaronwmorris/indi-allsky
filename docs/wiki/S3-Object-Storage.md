# S3 & Cloud Object Storage

`indi-allsky` supports direct automated uploading of images, keograms, star trails, and timelapses to cloud object storage providers using native SDK integrations (`boto3`, `google-cloud-storage`, `oci`).

Configuration is managed in the web dashboard under **Configuration** → **File Transfer**.

---

## 1. Amazon Web Services (AWS S3)

Transfer type: **`BOTO3_S3`**

### Configuration Parameters
* **Access Key ID**: AWS IAM access key.
* **Secret Access Key**: AWS IAM secret access key.
* **Region**: The AWS region hosting the bucket (e.g., `us-east-1`, `eu-west-1`).
* **Bucket Name**: Name of the target S3 bucket.
* **Path / Prefix**: Optional folder structure within the bucket (e.g., `allsky/`).
* **ACL**: Access control level (e.g., `public-read` or `private`).

### Recommended IAM Policy
Create an IAM user with restricted permissions limited to the destination bucket:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

---

## 2. Google Cloud Storage (GCS)

Transfer type: **`GCP_STORAGE`**

### Service Account Setup
1. Navigate to the Google Cloud Console: **IAM & Admin** → **Service Accounts**.
2. Click **Create Service Account**.
   * Specify a service account name (e.g., `indi-allsky-uploader`).
   * Grant the **Storage Object Admin** (or **Storage Object Creator**) role.
3. Select the created service account, navigate to **Keys** → **Add Key** → **Create new key**.
4. Select **JSON** format and download the credential file.
5. Place the downloaded JSON file on the allsky host (for example, `/etc/indi-allsky/gcp-credentials.json`) and verify permissions:
   ```bash
   sudo chown indi-allsky:indi-allsky /etc/indi-allsky/gcp-credentials.json
   sudo chmod 600 /etc/indi-allsky/gcp-credentials.json
   ```
6. Enter this file path into the **Credentials File** configuration field.

### Public Bucket Access (Optional)
If public web viewing is required without signed URLs:
1. Navigate to **Cloud Storage** → **Buckets** → select your bucket → **Permissions**.
2. Grant access to principal `allUsers` with the **Storage Object Viewer** role.

---

## 3. Oracle Cloud Infrastructure (OCI Object Storage)

Transfer type: **`OCI_STORAGE`**

### Configuration Requirements
OCI uses native API signing keys configured via standard OCI configuration files:

1. Generate an API signing key pair in the OCI Console under **Identity** → **Users** → **User Details** → **API Keys**.
2. Create an OCI config file on the host at `/etc/indi-allsky/oci_config`:
   ```ini
   [DEFAULT]
   user=ocid1.user.oc1..aaaaaaa...
   fingerprint=xx:xx:xx:xx:xx:...
   key_file=/etc/indi-allsky/oci_api_key.pem
   tenancy=ocid1.tenancy.oc1..aaaaaaa...
   region=us-ashburn-1
   ```
3. Set secure permissions:
   ```bash
   sudo chown -R indi-allsky:indi-allsky /etc/indi-allsky/oci*
   sudo chmod 600 /etc/indi-allsky/oci_config /etc/indi-allsky/oci_api_key.pem
   ```
4. Enter `/etc/indi-allsky/oci_config` in the **Credentials File** field.
5. Specify your tenancy **Namespace** and target **Bucket Name**.

---

## 4. S3-Compatible Storage (MinIO, Backblaze B2, Cloudflare R2)

Transfer type: **`BOTO3_MINIO`** or **`BOTO3_GENERIC`**

For third-party object storage platforms adhering to the S3 API protocol:

| Provider | Endpoint URL Example | Notes |
|---|---|---|
| **MinIO** | `http://minio.lan:9000` | Supports custom self-hosted endpoints; TLS verification bypass available for internal certificates. |
| **Backblaze B2** | `https://s3.us-west-004.backblazeb2.com` | Use S3-compatible Application Key credentials. |
| **Cloudflare R2** | `https://<account-id>.r2.cloudflarestorage.com` | Use R2 API Tokens with Object Read & Write permissions. |
| **Wasabi** | `https://s3.us-east-1.wasabisys.com` | Set corresponding region and endpoint URL. |