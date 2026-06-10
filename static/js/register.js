document.addEventListener("DOMContentLoaded", () => {
    const regForm = document.getElementById("register-form");
    const webcamSection = document.getElementById("webcam-section");
    const video = document.getElementById("webcam");
    const statusText = document.getElementById("status-text");
    const wrapper = document.getElementById("webcam-wrapper");
    const startBtn = document.getElementById("start-capture-btn");
    const progressBar = document.getElementById("progress-bar");
    const progressText = document.getElementById("progress-text");
    
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    canvas.width = 640;
    canvas.height = 480;
    
    let stream = null;
    let studentId = null;
    let studentName = "";
    let sampleCount = 0;
    const targetSamples = 100;
    let isCapturing = false;
    let captureInterval = null;

    if (regForm) {
        regForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            const name = document.getElementById("student-name").value.trim();
            const username = document.getElementById("student-username").value.trim();
            const roll_number = document.getElementById("student-roll").value.trim();
            const department = document.getElementById("student-dept").value.trim();
            const year = document.getElementById("student-year").value;
            
            if (!name || !username || !roll_number || !department || !year) {
                alert("Please fill in all fields.");
                return;
            }
            
            // Register student in DB first
            try {
                const response = await fetch("/api/register_student", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name, username, roll_number, department, year })
                });
                const data = await response.json();
                
                if (data.status === "success") {
                    studentId = data.student_id;
                    studentName = name;
                    
                    // Hide form and show webcam
                    regForm.classList.add("d-none");
                    webcamSection.classList.remove("d-none");
                    
                    // Start camera
                    await startWebcam();
                } else {
                    alert(data.message || "Registration failed.");
                }
            } catch (err) {
                console.error("Database registration error: ", err);
                alert("Error connecting to server. Please try again.");
            }
        });
    }

    async function startWebcam() {
        try {
            statusText.innerText = "Initializing camera...";
            stream = await navigator.mediaDevices.getUserMedia({
                video: { width: 640, height: 480, facingMode: "user" }
            });
            video.srcObject = stream;
            video.play();
            
            wrapper.classList.add("active");
            statusText.innerText = "Ready to record. Look directly at the camera and press 'Start Capturing'.";
            startBtn.disabled = false;
        } catch (err) {
            console.error("Error accessing webcam: ", err);
            statusText.innerHTML = '<span class="text-danger"><i class="fas fa-times-circle"></i> Camera access denied. Enable permissions and refresh.</span>';
            wrapper.classList.add("danger");
        }
    }

    function stopWebcam() {
        isCapturing = false;
        if (captureInterval) {
            clearInterval(captureInterval);
            captureInterval = null;
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
        if (video) {
            video.srcObject = null;
        }
        wrapper.classList.remove("scanning");
    }

    if (startBtn) {
        startBtn.addEventListener("click", () => {
            if (isCapturing) return;
            
            isCapturing = true;
            startBtn.disabled = true;
            wrapper.classList.add("scanning");
            statusText.innerText = "Capturing face samples... Move your head slightly.";
            
            // Capture a frame every 120ms to allow movement and give visual flash
            captureInterval = setInterval(captureAndUploadFrame, 120);
        });
    }

    function captureAndUploadFrame() {
        if (!isCapturing) return;
        
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
        
        sampleCount++;
        
        fetch("/api/register_face", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                student_id: studentId,
                student_name: studentName,
                image: dataUrl,
                sample_index: sampleCount
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === "success") {
                // Update progress bar
                const percentage = Math.round((sampleCount / targetSamples) * 100);
                progressBar.style.width = `${percentage}%`;
                progressBar.setAttribute("aria-valuenow", percentage);
                progressText.innerText = `Captured ${sampleCount} / ${targetSamples} samples`;
                
                if (sampleCount >= targetSamples) {
                    // Registration complete!
                    stopWebcam();
                    wrapper.classList.remove("active");
                    wrapper.classList.add("success");
                    statusText.innerHTML = `<span class="text-success"><i class="fas fa-check-circle"></i> Successfully registered face for ${studentName}!</span>`;
                    
                    // Show a link to train page
                    const actionContainer = document.getElementById("action-container");
                    actionContainer.innerHTML = `
                        <div class="mt-4 text-center">
                            <a href="/admin" class="btn btn-success-custom"><i class="fas fa-cogs me-2"></i> Go to Dashboard to Train</a>
                            <a href="/admin" class="btn btn-outline-light ms-2"><i class="fas fa-home me-2"></i> Admin Control Center</a>
                        </div>
                    `;
                }
            } else {
                // If it failed to detect face, decrement count and let it retry in the next frame
                sampleCount--;
                statusText.innerHTML = `<span class="text-warning"><i class="fas fa-exclamation-triangle"></i> Keep face in frame. Retrying capture...</span>`;
            }
        })
        .catch(err => {
            console.error("Frame upload error: ", err);
            sampleCount--;
        });
    }

    window.addEventListener("beforeunload", () => {
        stopWebcam();
    });
});
