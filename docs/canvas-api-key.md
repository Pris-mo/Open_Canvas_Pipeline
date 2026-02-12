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


[image1]: imgs/image1.png
[image2]: imgs/image2.png
[image3]: imgs/image3.png
[image4]: imgs/image4.png