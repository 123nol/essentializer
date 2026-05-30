!(import! &self ../../petta_chainer)

!(import! &self ../metamath_axioms)

; === PeTTaChainer Script for Goal 0 ===
!(compileadd kb (: local-hyp-72db6423-0 (Not (∨ (v0) (v1))) (STV 1.0 1.0)))
!(query 10 kb (: $prf (Not (∧ (v0) (Not (v1)))) $tv))

; --- Cleanup ---
;; cleanup needed