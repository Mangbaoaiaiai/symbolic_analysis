
; 不等价测试约束3B
(set-info :status unknown)
(declare-fun z () (_ BitVec 32))
(assert (bvuge z (_ bv6 32)))
(assert (bvule z (_ bv10 32)))
(check-sat)
