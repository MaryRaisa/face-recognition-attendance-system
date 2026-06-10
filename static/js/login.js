document.addEventListener("DOMContentLoaded", () => {
    const video = document.getElementById("webcam");
    const statusText = document.getElementById("status-text");
    const wrapper = document.getElementById("webcam-wrapper");
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    
    let stream = null;
    let scanInterval = null;
    let isScanning = false;
    let timeoutTimer = null;
    const timeoutDuration = 45000; // 45 seconds timeout
    
    // Set video frame capture sizes
    canvas.width = 640;
    canvas.height = 480;

    async function startWebcam() {
        try {
            statusText.innerText = "Initializing camera...";
            stream = await navigator.mediaDevices.getUserMedia({
                video: { width: 640, height: 480, facingMode: "user" }
            });
            video.srcObject = stream;
            video.play();
            
            // UI States
            wrapper.classList.add("active", "scanning");
            isScanning = true;
            statusText.innerText = "Scanning face... Position your face in the center.";
            
            // Start capturing frames
            scanInterval = setInterval(captureFrame, 1000); // Scan every 1 second
            
            // Start timeout countdown
            timeoutTimer = setTimeout(() => {
                stopWebcam();
                statusText.innerHTML = '<span class="text-warning"><i class="fas fa-exclamation-triangle"></i> Timeout. No face matched. Please try again.</span>';
                wrapper.classList.remove("scanning");
                wrapper.classList.add("danger");
            }, timeoutDuration);
            
        } catch (err) {
            console.error("Error accessing webcam: ", err);
            statusText.innerHTML = '<span class="text-danger"><i class="fas fa-times-circle"></i> Camera access denied. Enable permissions and refresh.</span>';
            wrapper.classList.add("danger");
        }
    }

    function stopWebcam() {
        isScanning = false;
        if (scanInterval) {
            clearInterval(scanInterval);
            scanInterval = null;
        }
        if (timeoutTimer) {
            clearTimeout(timeoutTimer);
            timeoutTimer = null;
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
        if (video) {
            video.srcObject = null;
        }
        wrapper.classList.remove("scanning");
    }

    function captureFrame() {
        if (!isScanning) return;
        
        // Draw the current video frame onto the canvas
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        
        // Convert to base64 jpeg
        const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
        
        // POST to backend API
        fetch("/api/login_face", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ image: dataUrl })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === "success") {
                // Stop scanning
                stopWebcam();
                
                // Success animations
                wrapper.classList.remove("active");
                wrapper.classList.add("success");
                statusText.innerHTML = `<span class="text-success"><i class="fas fa-check-circle"></i> Welcome, ${data.name}! Redirecting...</span>`;
                
                // Redirect after 1.5 seconds
                setTimeout(() => {
                    window.location.href = data.redirect;
                }, 1500);
            } else if (data.status === "unknown") {
                statusText.innerText = "Face not recognized. Keep looking at the camera...";
            } else if (data.status === "duplicate") {
                stopWebcam();
                wrapper.classList.remove("active");
                wrapper.classList.add("success");
                statusText.innerHTML = `<span class="text-info"><i class="fas fa-info-circle"></i> ${data.name}: Attendance already logged today. Redirecting...</span>`;
                setTimeout(() => {
                    window.location.href = data.redirect;
                }, 2000);
            } else {
                statusText.innerText = "Detecting face... Ensure good lighting.";
            }
        })
        .catch(err => {
            console.error("API Error: ", err);
        });
    }

    // Initialize
    if (video) {
        startWebcam();
    }
    
    // Cleanup on page navigate away
    window.addEventListener("beforeunload", () => {
        stopWebcam();
    });
});
