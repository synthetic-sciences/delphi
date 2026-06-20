// Package notify sends user notifications over email.
package notify

import "fmt"

// Notifier delivers messages to users.
type Notifier struct {
	from string
}

// NewNotifier constructs a Notifier with a sender address.
func NewNotifier(from string) *Notifier {
	return &Notifier{from: from}
}

// SendEmail delivers an email notification to a recipient.
func (n *Notifier) SendEmail(to string, subject string, body string) error {
	if to == "" {
		return fmt.Errorf("recipient address is required")
	}
	// Pretend to dispatch via an SMTP transport.
	fmt.Printf("from=%s to=%s subject=%s\n", n.from, to, subject)
	return nil
}
