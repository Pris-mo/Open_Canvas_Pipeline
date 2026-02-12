# **Configure Open WebUI & Pipelines**

Now that everything is running, we’ll configure Open WebUI so it can:

1. Allow API access  
2. Connect to Pipelines  
3. Install the Canvas provisioning pipeline

You’ll complete these steps inside the Open WebUI interface.

If you don’t already have your keys set up, you will need to do these first:

- **Open-WebUI Key (required):** [Get a Open-WebUI Key](./open-webui-api.md) 
- **Canvas API key (required):** [Get a Canvas API key](./canvas-api-key.md)  
- **OpenAI API key (optional):** [Get an OpenAI API key](./openai-api-key.md)

---

## **Connect Open WebUI to Pipelines**

Now we’ll create the internal connection between Open WebUI and the Pipelines service.

### **Step 1: Add a New Connection**

Navigate to:

**Admin Panel → Settings → Connections**

Click **Add Connection**

<details>
  <summary>Show screenshot</summary>

<img src="imgs/image18.png"
     alt="Screenshot"
     style="border: 1px solid #ccc; border-radius: 6px; padding: 4px;" />


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

  ![][image21]

</details>

If verification succeeds, click **Save**.

---

## **Install the Canvas Pipeline**

Now we’ll load the pipeline file from GitHub.

### **Step 1: Install from GitHub**

Navigate to:

**Admin Panel → Settings → Pipelines**

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

[Get a Canvas API key](./canvas-api-key.md)

---

### **OpenAI API Key (Optional)**

Paste your OpenAI key here if desired.  
If you don’t have one yet, see:

[Get an OpenAI API key](./openai-api-key.md)

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
https://docs.openwebui.com/getting-started/quick-start/starting-with-ollama/

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

[image19]: imgs/image19.png  
[image20]: imgs/image20.png  
[image21]: imgs/image21.png  
[image22]: imgs/image22.png  
[image23]: imgs/image23.png  
[image24]: imgs/image24.png
