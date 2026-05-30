!(import! &self ../../petta_chainer)

!(import! &self ../metamath_axioms)

; === PeTTaChainer Script for Goal 0 ===
!(compileadd kb (: local-hyp-42427790-0 (Implication
   (Premises (v0))
   (Conclusions (v1))
) (STV 1.0 1.0)))
!(compileadd kb (: local-hyp-42427790-1 (Not (v1)) (STV 1.0 1.0)))
!(query 10 kb (: $prf (Not (v0)) $tv))

; --- Cleanup ---
;; cleanup needed
;; cleanup needed