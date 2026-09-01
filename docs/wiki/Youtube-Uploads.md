# Setup
* Sign up for a Google Cloud Account
    * https://console.cloud.google.com/
    * This will require a credit card, though there is no cost for uploading videos to Youtube.
* Navigate to `IAM & Admin` -> `Create Project`
    * Give the project a name
* Switch to new project in drop down
* Navigate to `APIs & Services` -> `Library`
    * Find `YouTube Data API v3`
    * Enable the API
* Navigate to `APIs & Services` -> `Oauth consent screen`
    * Add your Youtube account to the Test users
    * You do *NOT* need to set your application to Production status
* Navigate to `APIs & Services` -> `Credentials`
    * Click `CREATE CREDENTIALS`
        * `OAuth client ID`
        * Application Type: `Web application`
        * Set name
        * Add `Authorized redirect URIs` from your Config page
            * This part is tricky.  The Redirect URI must use a valid TLD like .com / .net / etc.  **Your URL cannot end with .local.**  If you are hosting on your local network, just create a fake `/etc/hosts` entry to a fake .com.  Something like `fakeallsky.com` should work fine.  Navigate to this fake entry to get the proper Redirect URI by entering https://fakeallsky.com/indi-allsky/ in your browser.
            * The Redirect URI needs to be the full URL:
                * `https://fakeallsky.com/indi-allsky/youtube/oauth2callback`
            * The /etc/hosts entry should be created on the workstation running the browser based authorization process.
                * Windows:  `C:\Windows\System32\drivers\etc\hosts`
            * You only need to use the fake URL during the OAuth2 authorization process.  Once that is complete, you may use your normal URL.
        * Create
        * Download JSON credentials
* In the Config tab in indi-allsky, add the file location to the client-secrets.json file.
    * The file must be on the filesystem of the indi-allsky server
* Save config
* Click `Authorize` button to start the OAuth2 process.  You will have to select your Youtube account and sign-in to authorize indi-allsky to upload to your Youtube account.  You may have to approve the Multi-factor requests on your mobile device as well.
    * Assuming everything is setup correctly, you will see a very scary warning because your Google Cloud Platform application is not approved.  Click `Advanced` and proceed with the approval.
    * At this point, you are more likely to see problems.
        * If your URL does not end in a real TLD, you will receive a vague error.
        * If your Redirect URI does not match what was used in the credential setup, you will receive a `redirect_uri` error.


## Uploading
Once you enable uploads, you may click the `Upload to YouTube` button in the video viewer view to upload individual videos.

Uploads should start within 15-20 seconds of clicking the button.  The amount of time required depends on your Internet connection upload speed.

The indi-allsky capture service must be running for uploads to complete.


## Quotas
Every API call incurs a quota cost (not a monetary cost).  Most accounts start with a quota allocation of 10,000 units.  Uploading a video incurs a 1600 quota point cost.  You should be able to upload 6 videos per day with the default quota.

* https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits
* https://developers.google.com/youtube/v3/determine_quota_cost


## Notes

### Multiple indi-allsky systems
If you have multiple indi-allsky systems uploading to YouTube, you should create each credential in separate projects.  Failure to do so might result in the `refresh_token` not being generated in the client credentials which will cause uploads to eventually fail.


## Common problems
Some users will have their videos marked as `locked as private` preventing the videos from ever being set as Public.  There is no workaround for this.

https://github.com/tokland/youtube-upload/issues/306

### Note on Youtube Shorts
Please note that any video uploaded in a square aspect ratio (1:1) that is under three minutes long is automatically classified and uploaded by YouTube as a Short. If your all-sky camera sensor is square, the video will appear in your channel's Shorts section.

To prevent this, you can add an Image Border by navigating to the `Config > Image` menu to convert your video into a wider horizontal aspect ratio.