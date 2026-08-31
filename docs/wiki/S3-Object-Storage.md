#

## AWS

## Google Cloud
- Navigate to `IAM & Admin` -> `Service accounts`
- Click `CREATE SERVICE ACCOUNT` at the top
    - Set the service account name
    - Click `CREATE AND CONTINUE`
    - Grant `Storage Object Admin` role
    - Click `Done` at bottom
- On the new service account, click the vertical ellipsis at the right, and `Manage keys`
    - Click `ADD KEY` -> `Create new key`
    - JSON Key type
    - Click `CREATE`

The JSON file should automatically download.  This is the file you place on the filesystem and then in the path in the config field.

### Bucket setup
* Navigate to `Permissions` for the bucket
* Set `allUsers` principal to `Storage Object Viewer`

All objects in the bucket are now public and you do not need to specify the ACL.


## Oracle OCI