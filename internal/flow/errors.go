package flow

type NodeError struct {
	NodeID int64
	Type   string
	Err    error
}

func (e NodeError) Error() string {
	if e.Err == nil {
		return ""
	}
	return e.Err.Error()
}

func (e NodeError) Unwrap() error {
	return e.Err
}

func WrapNodeError(node *Node, err error) error {
	if err == nil {
		return nil
	}
	if _, ok := err.(NodeError); ok {
		return err
	}
	return NodeError{NodeID: node.ID, Type: node.Type, Err: err}
}
