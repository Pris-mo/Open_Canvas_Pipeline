# **Get Your Canvas LMS API Key**

To allow the system to access your course content, you’ll need a **Canvas API key** (sometimes called an “access token”).

An API key lets this application securely connect to your Canvas account to retrieve course materials. It does **not** give the application access to your password.

---

**⚠️ Important:**  
 Not all Canvas instances allow students to generate API keys.  
 If you don’t see the option described below, you may need to contact your Canvas administrator or IT department for help.

---

### **Step 1: Log in to Canvas**

Go to your institution’s Canvas site and log in.

---

### **Step 2: Open Account Settings**

1. Click **Account** in the left sidebar

2. Click **Settings**

<details>
  <summary>Show screenshot</summary>

  ![][image1]

</details>

---

### **Step 3: Generate a New Access Token**

1. Scroll down to the **Approved Integrations** section

2. Click **\+ New Access Token**

<details>
  <summary>Show screenshot</summary>

  ![][image2]

</details>


3. Give the token a name (for example: `Open_Canvas_Pipeline`)

4. (Optional) Set an expiration date

5. Click **Generate Token**

<details>
  <summary>Show screenshot</summary>

  ![][image3]

</details>


---

### **Step 4: Copy and Save Your Token**

Canvas will now display your API token.

⚠️ **Important:** This is the only time Canvas will show you the full token.  
 Copy it and save it somewhere secure.

<details>
  <summary>Show screenshot</summary>

  ![][image4]

</details>


---

### **If You Don’t See “New Access Token”**

Some institutions disable personal API token generation for students.

If you do not see the **\+ New Access Token** button:

* Contact your Canvas administrator or IT department

* Ask whether personal access tokens are enabled

* If not, ask whether they can generate one for you

---

# **Get Your OpenAI API Key (Optional)**

If you’d like to use OpenAI models (such as GPT-5-class models) inside the application, you’ll need an **OpenAI API key**.

An API key allows this application to securely send requests to OpenAI’s servers on your behalf. It does **not** share your password.

⚠️ This step is optional, but strongly recommended for new Open WebUI users. Adding an OpenAI API key enables higher-quality content retrieval and automatically makes OpenAI models available in your Open WebUI instance. 

---

### **Step 1: Create or Log In to Your OpenAI Account**

Go to:

👉 [https://platform.openai.com/](https://platform.openai.com/)

Sign in or create an account.

<details>
  <summary>Show screenshot</summary>

  ![][image5]

</details>


---

### **Step 2: Navigate to API Keys**

1. Click your profile icon (top right)  
2. Select **View API keys**  
    (or go directly to [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys))

<details>
  <summary>Show screenshot</summary>

  ![][image6]

</details>


---

### **Step 3: Create a New API Key**

1. Click **Create new secret key**

2. Give it a name (for example: `Open_Canvas_Pipeline`)

3. Click **Create**

<details>
  <summary>Show screenshot</summary>

  ![][image7]

</details>


---

### **Step 4: Copy and Save Your Key**

OpenAI will now display your API key.

⚠️ **Important:** This is the only time you’ll see the full key.  
 Copy it and store it somewhere secure.

<details>
  <summary>Show screenshot</summary>

  ![][image8]

</details>


## **Add Prepaid Billing to Your OpenAI Account**

---

### **Recommendation**

When adding prepaid credits:

* Start with the **lowest available amount**

* Monitor usage in your OpenAI dashboard

* Increase only if needed

For typical experimentation and course use, small balances often last a long time.

# **Install Docker**

This project runs inside **Docker**, which is a tool that lets you run software in a self-contained environment.

Think of Docker like a lightweight virtual machine: it bundles the app and everything it needs (libraries, dependencies, system tools) so you don’t have to manually install and configure all of that yourself. It helps make sure the project runs the same way on every computer.

### **How to install Docker**

There are two main ways to install it:

* **Recommended (easiest):** Install **Docker Desktop**  
   \- [https://docs.docker.com/desktop/](https://docs.docker.com/desktop/)  
   This includes everything you need and works well for most users.

* **Advanced (command line only):**  
  \-  [https://docs.docker.com/engine/install/](https://docs.docker.com/engine/install/)  
  This is typically used on Linux systems or servers.

After installation, make sure Docker is running before continuing to the next steps.

# **Run the Application with Docker**

Now that Docker is installed, we’ll use it to start the application.

Docker uses a **compose file** (`docker-compose.yaml`) to define and run multiple services together. In this case, it starts:

* **Open WebUI** \- the main interface you’ll use

* **Pipelines** \- the background service that powers course ingestion and automation

---

### **1\. Download the Compose File**

Download the `docker-compose.yaml` file from this repository:

\- [https://github.com/Pris-mo/Open\_Canvas\_Pipeline/blob/main/docker-compose.yaml](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docker-compose.yaml)

Save it in a new folder on your computer (for example, `Open_Canvas_Pipeline`).

---

### **2\. (Optional) Add Your OpenAI API Key**

If you’d like OpenAI models available when the app starts, you can add your API key. See section Create an OpenAI API Key for more info.

Open `docker-compose.yaml` and find:

`- OPENAI_API_KEY=${OPENAI_API_KEY:-}`

Replace it with:

`- OPENAI_API_KEY=your_key_here`

Example:   
`- OPENAI_API_KEY=sk-proj-123abc`

This step is optional. The application will still run without it.

---

### **3\. Start the Application**

Open a terminal in the folder containing `docker-compose.yaml`, then run:

`docker compose up -d`

The `-d` flag runs everything in the background.

The first time you run this, Docker will download and set everything up.  
 This can take several minutes (\~5-10 minutes is normal).

---

### **4\. Open the Web Interface**

Once it finishes starting up, open your browser and go to:

\- [http://localhost:3000](http://localhost:3000)

You should see the Open WebUI interface. If the page is not loading, the application may still be building (Did you wait 5-10 minutes?). If you’ve waited long enough see troubleshooting below. 

---

### **5\. If Something Seems Stuck**

You can check what’s happening behind the scenes by viewing logs:

`docker logs -f open-webui`

or

`docker logs -f pipelines`

---

### **To Stop the Application**

If you want to shut everything down:

`docker compose down`

# **Configure Open WebUI & Pipelines**

Now that everything is running, we’ll configure Open WebUI so it can:

1. Allow API access  
2. Connect to Pipelines  
3. Install the Canvas provisioning pipeline

You’ll complete these steps inside the Open WebUI interface.

---

## **Enable API Access in Open WebUI**

### **Step 1: Open the Admin Panel**

1. Click your **profile icon** in the lower-left corner  
2. Select **Admin Panel**

<details>
  <summary>Show screenshot</summary>

  ![][image9]

</details>
  
---

### **Step 2: Create an Admin Group**

1. Navigate to **Users \-\> Groups**

<details>
  <summary>Show screenshot</summary>

  ![][image10]

</details>


2. Click **Create Group,** name it: `Admins`

<details>
  <summary>Show screenshot</summary>

  ![][image11]

</details>


3. Select **Permissions**, scroll down to **API Keys**, Toggle it to **On,** Then select **Save**

<details>
  <summary>Show screenshot</summary>

  ![][image12]

</details>

---

### **Step 3: Add Yourself to the Admin Group**

1. Open the **Admins** group, select **Users**

<details>
  <summary>Show screenshot</summary>

  ![][image13]

</details>


2. Add your user account

<details>
  <summary>Show screenshot</summary>

  ![][image14]

</details>
  
---

### **Step 4: Enable API Keys Globally**

1. Go to **Admin Panel \-\> Settings**  
2. Toggle **Enable API Keys**  
3. Click **Save**

<details>
  <summary>Show screenshot</summary>

  ![][image15]

</details>


## **Generate Your Open WebUI API Key**

You’ll need this key to allow the pipeline to communicate with Open WebUI.

1. Click your **profile icon,** select **Settings**  

   
<details>
  <summary>Show screenshot</summary>

  ![][image16]

</details>
  
2. Select **Account,** Click **API Keys \-\> Show**

<details>
  <summary>Show screenshot</summary>

  ![][image17]

</details>


3. Select **\+ Create new secret key**  
4. Copy and save the key securely

You’ll use this shortly.

---

## **Connect Open WebUI to Pipelines**

Now we’ll create the internal connection between Open WebUI and the Pipelines service.

### **Step 1: Add a New Connection**

Navigate to:

**Admin Panel \-\> Settings \-\> Connections**

Click **Add Connection**

<details>
  <summary>Show screenshot</summary>

  ![][image18]

</details>

---

### **Step 2: Enter Connection Details**

Set:

**URL:**  `http://pipelines:9099/v1`  
**Bearer Token:**  `0p3n-w3bu!`  

<details>
  <summary>Show screenshot</summary>

  ![][image19]

</details>


Then click **Verify Connection**.

<details>
  <summary>Show screenshot</summary>

  ![][image20]

</details>

<details>
  <summary>Show screenshot</summary>

  ![][image21]

</details>


If verification succeeds, click **Save**.

---

## **Install the Canvas Pipeline**

Now we’ll load the pipeline file from GitHub.

### **Step 1: Install from GitHub**

Navigate to:

**Admin Panel \-\> Settings \-\> Pipelines**

In the **Install from GitHub URL** field, enter:

`https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/canvas_course_provisioner.py`

Click the upload/install icon.

<details>
  <summary>Show screenshot</summary>

  ![][image22]

</details>


---

### **Step 2: Wait for Installation**

The system will:

* Download the file  
* Install dependencies  
* Initialize the pipeline

This can take anywhere from **30 seconds to 5+ minutes**, depending on your system.

<details>
  <summary>Show screenshot</summary>

  ![][image23]

</details>
  
---

## **Configure the Pipeline Settings**

Once installed, update the following fields:

---

### **OpenWebUI Base URL**

Default:

`http://open-webui:8080`

You typically do not need to change this.

---

### **OpenWebUI API Key**

Paste the key you generated earlier in:

 **Generate Your Open WebUI API Key**

---

### **Canvas API Key**

Paste the key retrieved from:

**Retrieve Canvas API Key**

---

### **OpenAI API Key (Optional)**

Paste your OpenAI key here if desired.

Including this enables:

* Higher-quality processing  
* Better handling of scanned or complex documents  
* Improved content retrieval

---

### **Base Model ID**

Enter the exact model name you want to use.

Default:

`GPT-5`

(You may use any model available in your Open WebUI instance.) To install local or other models see documentation here:  
[https://docs.openwebui.com/getting-started/quick-start/starting-with-ollama/](https://docs.openwebui.com/getting-started/quick-start/starting-with-ollama/)

---

### **Include Metadata**

Enable this if you want the assistant to reference:

* File URLs  
* Due dates  
* Points possible  
* Canvas metadata

Recommended: **On**

---

### **HTTP Timeout (Seconds)**

Increase this if:

* Files are failing to download  
* Large documents are timing out

Most users can leave this unchanged.

---

After completing all fields:

Click **Save**

<details>
  <summary>Show screenshot</summary>

  ![][image24]

</details>
  
---

# **🎉 Setup Complete**

Your Open WebUI instance is now:

* API-enabled  
* Connected to Pipelines  
* Configured with the Canvas provisioning system

You’re ready to begin provisioning courses.

[image1]: imgs/image1.png
[image2]: imgs/image2.png
[image3]: imgs/image3.png
[image4]: imgs/image4.png
[image5]: imgs/image5.png
[image6]: imgs/image6.png
[image7]: imgs/image7.png
[image8]: imgs/image8.png
[image9]: imgs/image9.png
[image10]: imgs/image10.png
[image11]: imgs/image11.png
[image12]: imgs/image12.png
[image13]: imgs/image13.png
[image14]: imgs/image14.png
[image15]: imgs/image15.png
[image16]: imgs/image16.png
[image17]: imgs/image17.png
[image18]: imgs/image18.png
[image19]: imgs/image19.png
[image20]: imgs/image20.png
[image21]: imgs/image21.png
[image22]: imgs/image22.png
[image23]: imgs/image23.png
[image24]: imgs/image24.png
