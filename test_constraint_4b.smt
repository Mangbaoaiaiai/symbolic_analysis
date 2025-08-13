
; 不等价测试约束4B
(set-info :status unknown)
(declare-fun w () (_ BitVec 32))
(assert (= w (_ bv1 32)))
(check-sat)
