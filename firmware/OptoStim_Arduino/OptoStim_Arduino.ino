// OptoStim_Arduino.ino
//
// Switches one output pin from single characters received over USB serial:
//   'B'  ->  pin HIGH  (laser on)
//   'N'  ->  pin LOW   (laser off)
// Any other character is ignored. The OptoStim app sends exactly these two.
//
// Wiring (Arduino Uno / Nano):
//   pin 7  ->  trigger input "+" (or "S"/"IN") of the MOSFET switch module
//   GND    ->  trigger input "-" (GND) of the module
//   The laser's own power supply goes to the module's power terminals, never to the Arduino.
//
// Upload with the Arduino IDE (Tools > Board, Tools > Port, then Upload).
// Close the IDE's Serial Monitor before using OptoStim: only one program can use the port.

const uint8_t LASER_PIN = 7;
const long BAUD_RATE = 9600;   // must match "Baud rate" in OptoStim

void setup() {
  pinMode(LASER_PIN, OUTPUT);
  digitalWrite(LASER_PIN, LOW);    // laser is off after power-up and after every reset
  Serial.begin(BAUD_RATE);
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'B') {
      digitalWrite(LASER_PIN, HIGH);
    } else if (c == 'N') {
      digitalWrite(LASER_PIN, LOW);
    }
  }
}
