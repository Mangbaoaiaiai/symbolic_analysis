
; 等价测试约束1A
(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
(assert (bvuge x (_ bv5 32)))
(assert (bvule x (_ bv10 32)))
(check-sat)
