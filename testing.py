# Test code
import cv2

# Initialize the camera (0 is usually the default built-in camera)
cap = cv2.VideoCapture(1)

while True:
    # Capture frame-by-frame
    ret, frame = cap.read()

    if not ret:
        break

    # Display the resulting frame
    cv2.imshow('Camera Feed', frame)

    # Press 'q' to exit the loop
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release resources when done
cap.release()
cv2.destroyAllWindows()
